"""Storing what the live editor sends: its Yjs state and the rows materialized from it (tasks 3.3 and 3.8).

One function serves the collaboration service's saves and Django's own snapshots (before submission, before a
comparison), so both follow the same order: under the version's row lock, never after the version left draft,
and never over a newer save.
"""

from dataclasses import dataclass, field

import sentry_sdk
import structlog
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.core.locking import VersionLocked
from apps.programs.models import ProgramVersion

from .materialization import MaterializationError, apply_rows
from .models import DraftDocument

log = structlog.get_logger("harak2.collab")


@dataclass
class Saved:
    stale: bool = False
    changed_blocks: list[str] = field(default_factory=list)
    skipped_links: list[str] = field(default_factory=list)


class SaveRejected(Exception):
    """The rows could not be applied. The state was stored (it is newer), the last good rows were kept."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def save_document(version: ProgramVersion, *, state: bytes, rows, actor=None, seq: int | None = None) -> Saved:
    """Stores the state and applies its rows. Raises VersionLocked or SaveRejected.

    `seq` orders saves of one document: a save numbered at or below the stored one is older than what Django
    holds and changes nothing. Saves without a number (tests, tools) always apply.
    """
    rejected: MaterializationError | None = None
    with transaction.atomic():
        # Only the version row is locked (of=self): the transition locks the program row after it.
        # Saves of one document run one at a time, and never after the version left draft: the lock conflicts
        # with the transition's (FOR NO KEY UPDATE) and with REST writes (FOR UPDATE).
        locked = (
            ProgramVersion.objects.select_for_update(of=("self",))
            .select_related("program__template_version")
            .get(pk=version.pk)
        )
        if not locked.is_editable:
            raise VersionLocked()
        draft, _ = DraftDocument.objects.get_or_create(version=locked, defaults={"state": b""})
        if seq is not None and seq <= draft.saved_seq:
            return Saved(stale=True)
        draft.state = state
        draft.state_hash = DraftDocument.hash_of(state)
        if seq is not None:
            draft.saved_seq = seq
        try:
            with transaction.atomic():
                result = apply_rows(locked, rows, actor=actor)
        except MaterializationError as exc:
            rejected = exc
            _note_error(draft, str(exc), exc.code)
        else:
            draft.materialized_at = timezone.now()
            draft.issues = list((rows or {}).get("issues", [])) if isinstance(rows, dict) else []
            draft.last_error = ""
            draft.last_error_code = ""
            draft.last_error_at = None
        draft.save()
    if rejected is not None:
        _alert(locked, str(rejected), rejected.code)
        raise SaveRejected(str(rejected), rejected.code)
    return Saved(changed_blocks=result["changed_blocks"], skipped_links=result["skipped_links"])


def editor(actor_id) -> User | None:
    """The member the editor names as the last to change the document (links they made are theirs)."""
    if actor_id and Membership.objects.filter(user_id=actor_id).exists():
        return User.objects.filter(pk=actor_id).first()
    return None


def record_failure(version: ProgramVersion, error: str, code: str = "document_invalid") -> None:
    """The editor could not turn its document into rows at all. Rows and state stay as last saved."""
    if not version.is_editable:
        return  # Nothing left to block: the version was submitted with its last good rows.
    if code not in MaterializationError.CODES:
        code = "document_invalid"
    draft, _ = DraftDocument.objects.get_or_create(version=version, defaults={"state": b""})
    _note_error(draft, error, code)
    draft.save(update_fields=["last_error", "last_error_code", "last_error_at", "updated_at"])
    _alert(version, error, code)


def _note_error(draft: DraftDocument, error: str, code: str) -> None:
    # Submission stays blocked until a later save of this draft succeeds.
    draft.last_error = error[:2000]
    draft.last_error_code = code
    draft.last_error_at = timezone.now()


def _alert(version: ProgramVersion, error: str, code: str) -> None:
    log.error(
        "collab.materialization_failed",
        version=version.pk,
        organization=version.organization_id,
        code=code,
        error=error,
    )
    sentry_sdk.capture_message(f"materialization failed for version {version.pk}: {error}", level="error")
