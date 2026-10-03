"""The live document follows its version's lifecycle (tasks 3.4 and 3.8)."""

import structlog
from django.db import transaction
from django.dispatch import receiver

from apps.programs import lifecycle

from . import client
from .models import DraftDocument
from .tokens import document_name

log = structlog.get_logger("harak2.collab")


@receiver(lifecycle.leaving_draft)
def flush_before_leaving_draft(sender, version, target, **kwargs):
    """The rows must reflect the live document before a draft is submitted or cancelled.

    Flush is asked for even when Django has no stored state yet: the document may be open
    with edits that have not reached their first save.
    """
    try:
        result = client.call("flush", document_name(version))
    except client.CollabUnavailable as exc:
        log.warning("collab.flush_unavailable", version=version.pk, error=str(exc))
        if not DraftDocument.objects.filter(version=version).exists():
            return  # Never edited live: the rows are the content.
        raise lifecycle.TransitionRefused(
            "the live editor cannot be reached to save the latest changes; try again in a moment",
            code="collab_unavailable",
        ) from exc
    draft = DraftDocument.objects.filter(version=version).first()
    if result.get("status") == "failed" or (draft is not None and draft.last_error):
        raise lifecycle.TransitionRefused(
            f"the latest changes could not be saved: {result.get('error') or draft.last_error}",
            code="materialization_failed",
        )


@receiver(lifecycle.left_draft)
def lock_after_leaving_draft(sender, version, **kwargs):
    def lock():
        try:
            client.call("lock", document_name(version))
        except client.CollabUnavailable as exc:
            # Django already refuses saves for a locked version; the editor locks itself on the next save.
            log.warning("collab.lock_unavailable", version=version.pk, error=str(exc))

    transaction.on_commit(lock)


@receiver(lifecycle.rows_requested)
def flush_before_reading_rows(sender, version, **kwargs):
    """Readers of a live draft's rows (comparison, analysis, export) see its latest content when possible."""
    if not version.is_editable:
        return
    try:
        client.call("flush", document_name(version))
    except client.CollabUnavailable as exc:
        log.warning("collab.flush_unavailable", version=version.pk, error=str(exc))
