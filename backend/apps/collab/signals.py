"""The live document follows its version's lifecycle (tasks 3.4 and 3.8).

Before a draft leaves draft status the live document is frozen: every editor turns read-only and the service
answers with the document as it stands, which Django stores and applies itself. Nothing typed after the
freeze can be lost silently, and nothing typed before it is missing from the submitted rows. The freeze ends
with a lock when the transition commits, or is released when the draft stays a draft.
"""

import base64
import binascii

import structlog
from django.conf import settings
from django.db import transaction
from django.dispatch import receiver

from apps.core.locking import VersionLocked
from apps.programs import lifecycle

from . import client
from .models import DraftDocument
from .saving import SaveRejected, editor, record_failure, save_document
from .tokens import document_name

log = structlog.get_logger("harak2.collab")

HELD_FREEZE = "collab_freeze"


class SnapshotUnusable(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def apply_snapshot(version, answer: dict) -> None:
    """Stores what a freeze or snapshot returned. Raises SnapshotUnusable, VersionLocked."""
    status = answer.get("status")
    if status == "not_loaded":
        return  # Nobody has it open: the stored state and rows are the latest content.
    if status == "failed":
        message = str(answer.get("error") or "the live document could not be read")
        record_failure(version, message, str(answer.get("code") or ""))
        raise SnapshotUnusable(message, "document_invalid")
    if status != "snapshot":
        raise SnapshotUnusable(f"unexpected answer from the live editor: {status!r}", "document_invalid")
    try:
        state = base64.b64decode(answer.get("state") or "", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SnapshotUnusable("the live editor sent a state that is not base64", "document_invalid") from exc
    seq = answer.get("seq")
    try:
        save_document(
            version,
            state=state,
            rows=answer.get("rows"),
            actor=editor(answer.get("actor_id")),
            seq=seq if isinstance(seq, int) else None,
        )
    except SaveRejected as exc:
        raise SnapshotUnusable(str(exc), exc.code) from exc


@receiver(lifecycle.leaving_draft)
def freeze_before_leaving_draft(sender, version, target, held, **kwargs):
    """The rows must be the live document's before a draft is submitted or cancelled.

    The freeze is asked for even when Django has no live state yet: the document may be loading, and
    a freeze keeps it read-only from the moment it opens.
    """
    name = document_name(version)
    try:
        answer = client.call("freeze", name)
    except client.CollabUnavailable as exc:
        log.warning("collab.freeze_unavailable", version=version.pk, error=str(exc))
        if not DraftDocument.objects.filter(version=version).exists():
            return  # Never edited live: the rows are the content.
        raise lifecycle.TransitionRefused(
            "the live editor cannot be reached to hand over the latest changes; try again in a moment",
            code="collab_unavailable",
        ) from exc
    if answer.get("token"):
        held[HELD_FREEZE] = (name, str(answer["token"]))
    try:
        apply_snapshot(version, answer)
    except SnapshotUnusable as exc:
        raise lifecycle.TransitionRefused(
            f"the latest changes could not be saved: {exc}", code="materialization_failed"
        ) from exc
    draft = DraftDocument.objects.filter(version=version).first()
    if draft is not None and draft.last_error:
        raise lifecycle.TransitionRefused(
            f"the latest changes could not be saved: {draft.last_error}", code="materialization_failed"
        )


@receiver(lifecycle.draft_kept)
def unfreeze_when_the_draft_stays(sender, version, held, **kwargs):
    if HELD_FREEZE not in held:
        return
    name, token = held.pop(HELD_FREEZE)
    try:
        client.call("unfreeze", name, query={"token": token})
    except client.CollabUnavailable as exc:
        # The service lifts a freeze nobody releases after a while, once Django confirms the draft is editable.
        log.warning("collab.unfreeze_unavailable", version=version.pk, error=str(exc))


@receiver(lifecycle.left_draft)
def lock_after_leaving_draft(sender, version, **kwargs):
    # The lock ends every freeze. Until the transaction commits the freeze stays held, so an error after this
    # point still releases it (draft_kept).

    def lock():
        try:
            client.call("lock", document_name(version))
        except client.CollabUnavailable as exc:
            # Django refuses saves of a locked version; the service locks itself on the next save it attempts.
            log.warning("collab.lock_unavailable", version=version.pk, error=str(exc))

    transaction.on_commit(lock)


@receiver(lifecycle.rows_requested)
def snapshot_before_reading_rows(sender, version, **kwargs):
    """Readers of a live draft's rows (comparison, analysis, export) see its latest content when possible.

    Best effort, and quick: when the editor is slow or the content cannot be applied, the reader gets the
    last saved rows rather than an error.
    """
    if not version.is_editable or not DraftDocument.objects.filter(version=version).exists():
        return
    try:
        answer = client.call("snapshot", document_name(version), timeout=settings.COLLAB_SNAPSHOT_TIMEOUT_SECONDS)
        apply_snapshot(version, answer)
    except (client.CollabUnavailable, SnapshotUnusable, VersionLocked) as exc:
        log.warning("collab.snapshot_skipped", version=version.pk, error=str(exc))
