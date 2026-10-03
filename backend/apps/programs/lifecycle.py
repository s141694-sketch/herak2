"""The single point through which a program version changes status (spec 6.1).

Phase 5 adds the conditions that guard some transitions (pre-submit check,
open must_fix comments, workflow stages); the table of what is possible at all
lives here.
"""

from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import Conflict
from apps.core.locking import lifecycle_write

from .copying import create_draft_copy
from .models import Program, ProgramVersion

S = ProgramVersion.Status

ALLOWED: set[tuple[str, str]] = {
    (S.DRAFT, S.SUBMITTED),
    (S.DRAFT, S.CANCELLED),
    (S.SUBMITTED, S.IN_STAGE),
    (S.SUBMITTED, S.WITHDRAWN),
    (S.SUBMITTED, S.CANCELLED),
    (S.IN_STAGE, S.IN_STAGE),
    (S.IN_STAGE, S.APPROVED),
    (S.IN_STAGE, S.RETURNED),
    (S.IN_STAGE, S.WITHDRAWN),
    (S.IN_STAGE, S.CANCELLED),
    (S.APPROVED, S.EXPORTED),
}

# Returning or withdrawing hands the content back to the authors as a new draft copy.
CREATES_DRAFT = {S.RETURNED, S.WITHDRAWN}

PROGRAM_STATUS = {
    S.DRAFT: Program.Status.DRAFT,
    S.SUBMITTED: Program.Status.IN_REVIEW,
    S.IN_STAGE: Program.Status.IN_REVIEW,
    S.APPROVED: Program.Status.APPROVED,
    S.EXPORTED: Program.Status.APPROVED,
    S.RETURNED: Program.Status.DRAFT,
    S.WITHDRAWN: Program.Status.DRAFT,
    S.CANCELLED: Program.Status.DRAFT,
}


class TransitionRefused(Conflict):
    default_code = "transition_refused"


# Sent before a draft changes status; receivers may refuse by raising TransitionRefused.
leaving_draft = Signal()
# Sent after a draft changed status, inside the transaction.
left_draft = Signal()
# Sent before a version's rows are read where freshness matters (comparison, analysis, export).
rows_requested = Signal()


def transition(version: ProgramVersion, to: str, *, actor, stage: int | None = None, payload: dict | None = None):
    current = ProgramVersion.objects.get(pk=version.pk)
    if current.status == S.DRAFT and (S.DRAFT, to) in ALLOWED:
        # Receivers may call other services (the live editor saves its rows through Django), so this
        # runs before any row lock is taken. The locked step below re-checks the status.
        leaving_draft.send(sender=ProgramVersion, version=current, target=to)
    return _transition(version, to, actor=actor, stage=stage, payload=payload)


@transaction.atomic
def _transition(version: ProgramVersion, to: str, *, actor, stage: int | None, payload: dict | None):
    # NO KEY UPDATE: rows that reference this version (nodes, blocks, audit entries) can still be written.
    version = ProgramVersion.objects.select_for_update(no_key=True).get(pk=version.pk)
    source = version.status
    if (source, to) not in ALLOWED:
        raise TransitionRefused(f"a {source} version cannot become {to}")
    if to == S.IN_STAGE:
        expected = (version.current_stage or 0) + 1 if source == S.IN_STAGE else 1
        if stage != expected:
            raise TransitionRefused(f"the next stage is {expected}", code="stage_out_of_order")
        version.current_stage = stage

    now = timezone.now()
    version.status = to
    if to == S.SUBMITTED:
        version.submitted_at = now
    if to == S.APPROVED:
        version.approved_by = actor
        version.approved_at = now
    with lifecycle_write():
        version.save()

    program = Program.objects.select_for_update().get(pk=version.program_id)
    program.status = PROGRAM_STATUS[to]
    program.save(update_fields=["status"])

    record(
        "program_version.transition",
        actor=actor,
        target=version,
        payload={"from": source, "to": to, "stage": version.current_stage, **(payload or {})},
    )
    if source == S.DRAFT:
        left_draft.send(sender=ProgramVersion, version=version, target=to)
    if to in CREATES_DRAFT:
        create_draft_copy(version, actor=actor)
    return version
