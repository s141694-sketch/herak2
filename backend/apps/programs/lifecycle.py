"""The single point through which a program version changes status (spec 6.1).

The table of what is possible at all lives here. The conditions of the approval workflow (pre-submit check,
open must_fix comments, who decides at which stage) live in apps.workflows, which passes them in as ``check``,
run under the version's row lock before anything changes, and ``then``, run in the same transaction after the
change was recorded (opening the next stage task, closing the submission).
"""

from collections.abc import Callable

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


# Sent before a draft changes status; receivers may refuse by raising TransitionRefused. Every receiver of the
# three draft signals gets `held`, one dict per transition, to keep what it took (a freeze) until the outcome.
leaving_draft = Signal()
# Sent after a draft changed status, inside the transaction.
left_draft = Signal()
# Sent when a draft that was leaving stays a draft (a refusal or an error), so receivers release what they took.
draft_kept = Signal()
# Sent before a version's rows are read where freshness matters (comparison, analysis, export).
rows_requested = Signal()


Hook = Callable[[ProgramVersion], None] | None


def transition(
    version: ProgramVersion,
    to: str,
    *,
    actor,
    stage: int | None = None,
    payload: dict | None = None,
    check: Hook = None,
    then: Hook = None,
):
    current = ProgramVersion.objects.get(pk=version.pk)
    hooks = {"check": check, "then": then}
    if not (current.status == S.DRAFT and (S.DRAFT, to) in ALLOWED):
        return _transition(version, to, actor=actor, stage=stage, payload=payload, held={}, **hooks)
    held: dict = {}
    try:
        # Receivers may call other services (the live editor hands over its latest content), so this runs
        # before any row lock is taken. The locked step below re-checks the status.
        leaving_draft.send(sender=ProgramVersion, version=current, target=to, held=held)
        return _transition(version, to, actor=actor, stage=stage, payload=payload, held=held, **hooks)
    except BaseException:
        draft_kept.send_robust(sender=ProgramVersion, version=current, held=held)
        raise


@transaction.atomic
def _transition(
    version: ProgramVersion,
    to: str,
    *,
    actor,
    stage: int | None,
    payload: dict | None,
    held: dict,
    check: Hook = None,
    then: Hook = None,
):
    # NO KEY UPDATE: rows that reference this version (nodes, blocks, audit entries) can still be written.
    version = ProgramVersion.objects.select_for_update(no_key=True).get(pk=version.pk)
    source = version.status
    if (source, to) not in ALLOWED:
        raise TransitionRefused(f"a {source} version cannot become {to}")
    if to == S.IN_STAGE:
        # From one stage only to the next; a submission enters at the stage its workflow names (D54).
        if source == S.IN_STAGE and stage != (version.current_stage or 0) + 1:
            raise TransitionRefused(f"the next stage is {version.current_stage + 1}", code="stage_out_of_order")
        if source == S.SUBMITTED and (stage is None or stage < 1):
            raise TransitionRefused("a submission enters a stage numbered from 1", code="stage_out_of_order")
        version.current_stage = stage
    if check is not None:
        check(version)

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
        left_draft.send(sender=ProgramVersion, version=version, target=to, held=held)
    if to in CREATES_DRAFT:
        create_draft_copy(version, actor=actor)
    if then is not None:
        then(version)
    return version
