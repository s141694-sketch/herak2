"""The approval workflow (spec 6.1-6.3, tasks 5.1-5.3).

Every status change still goes through apps.programs.lifecycle.transition; this module decides which change a
request leads to and passes its conditions in as checks that run under the version's row lock. Locks are taken
in one order everywhere: the version first, then the workflow's rows.
"""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, Role
from apps.audit.services import record
from apps.core.errors import Conflict
from apps.programs import lifecycle
from apps.programs.models import Program, ProgramVersion
from apps.programs.services import can_edit

from . import rules
from .models import (
    STAGE_ROLES,
    ProgramWorkflow,
    Resubmit,
    StageDecision,
    StageTask,
    WorkflowInstance,
    WorkflowTemplate,
)
from .workdays import add_work_days

S = ProgramVersion.Status
MAX_STAGES = 20
MAX_DUE_WORK_DAYS = 365
MAX_NOTE = 5000


class WorkflowError(Conflict):
    default_code = "workflow_error"


class NotAllowed(WorkflowError):
    status_code = 403
    default_code = "permission_denied"
    default_detail = "you may not do this"


# --- Templates (task 5.2) ----------------------------------------------------------------------------------


def _clean_stages(stages) -> list[dict]:
    if not isinstance(stages, list) or not stages:
        raise WorkflowError("a workflow needs at least one stage", code="workflow_stages_required")
    if len(stages) > MAX_STAGES:
        raise WorkflowError(f"a workflow has at most {MAX_STAGES} stages", code="workflow_stages_too_many")
    active = set(Membership.objects.exclude(role=Role.PENDING).values_list("user_id", flat=True))
    cleaned = []
    for order, stage in enumerate(stages, start=1):
        invalid = WorkflowError(f"stage {order} is not valid", code="workflow_stage_invalid")
        if not isinstance(stage, dict):
            raise invalid
        name = str(stage.get("name") or "").strip()
        user = stage.get("assignee_user")
        stage_role = stage.get("assignee_role") or ""
        days = stage.get("due_work_days")
        resubmit = stage.get("resubmit") or Resubmit.SAME_STAGE
        if not name or len(name) > 200:
            raise invalid
        if (user is None) == (stage_role == ""):  # exactly one of a person or a role
            raise invalid
        if user is not None and (not isinstance(user, int) or user not in active):
            raise invalid
        if stage_role and stage_role not in STAGE_ROLES:
            raise invalid
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= MAX_DUE_WORK_DAYS:
            raise invalid
        if resubmit not in Resubmit.values:
            raise invalid
        cleaned.append(
            {
                "order": order,
                "name": name,
                "assignee_user": user,
                "assignee_role": stage_role,
                "due_work_days": days,
                "resubmit": resubmit,
            }
        )
    return cleaned


@transaction.atomic
def save_template(template: WorkflowTemplate | None, *, actor, name: str, stages, is_default: bool = False):
    """Creates a template, or replaces an existing one's name and stages (running reviews keep their copy)."""
    name = (name or "").strip()
    if not name or len(name) > 200:
        raise WorkflowError("the workflow needs a name", code="workflow_name_invalid")
    cleaned = _clean_stages(stages)
    if is_default:
        others = WorkflowTemplate.objects.filter(is_default=True)
        if template is not None:
            others = others.exclude(pk=template.pk)
        others.update(is_default=False)
    if template is None:
        template = WorkflowTemplate.objects.create(name=name, is_default=is_default, created_by=actor)
        event = "workflow_template.created"
    else:
        template = WorkflowTemplate.objects.select_for_update().get(pk=template.pk)
        template.name, template.is_default = name, is_default
        template.save()
        template.stages.all().delete()
        event = "workflow_template.updated"
    for stage in cleaned:
        template.stages.create(
            order=stage["order"],
            name=stage["name"],
            assignee_user_id=stage["assignee_user"],
            assignee_role=stage["assignee_role"],
            due_work_days=stage["due_work_days"],
            resubmit=stage["resubmit"],
        )
    record(event, actor=actor, target=template, payload={"name": name, "stages": cleaned, "default": is_default})
    return template


@transaction.atomic
def delete_template(template: WorkflowTemplate, *, actor) -> None:
    if ProgramWorkflow.objects.filter(template=template).exists():
        raise WorkflowError("programs follow this workflow", code="workflow_in_use")
    record("workflow_template.deleted", actor=actor, target=template, payload={"name": template.name})
    template.delete()


@transaction.atomic
def choose_template(program: Program, template: WorkflowTemplate | None, *, actor) -> None:
    """The template a program follows; None returns it to the organization's default."""
    if template is None:
        ProgramWorkflow.objects.filter(program=program).delete()
    else:
        ProgramWorkflow.objects.update_or_create(program=program, defaults={"template": template})
    record(
        "program.workflow_chosen", actor=actor, target=program, payload={"template": template.pk if template else None}
    )


def template_for(program: Program) -> WorkflowTemplate | None:
    choice = ProgramWorkflow.objects.filter(program=program).select_related("template").first()
    if choice is not None:
        return choice.template
    return WorkflowTemplate.objects.filter(is_default=True).first()


def _snapshot(template: WorkflowTemplate) -> list[dict]:
    return [
        {
            "order": stage.order,
            "name": stage.name,
            "assignee_user": stage.assignee_user_id,
            "assignee_role": stage.assignee_role,
            "due_work_days": stage.due_work_days,
            "resubmit": stage.resubmit,
        }
        for stage in template.stages.order_by("order")
    ]


# --- Submission and the way through the stages (task 5.3) --------------------------------------------------


def _returned_from(version: ProgramVersion) -> WorkflowInstance | None:
    """The submission this draft answers, when its source version was returned (D54)."""
    source = version.source_version
    if source is None or source.status != S.RETURNED:
        return None
    return WorkflowInstance.objects.filter(version=source, outcome=WorkflowInstance.Outcome.RETURNED).first()


def _open_task(instance: WorkflowInstance, stage: int, now) -> StageTask:
    spec = instance.stages[stage - 1]
    work_days = instance.organization.work_days
    return StageTask.objects.create(
        instance=instance,
        stage=stage,
        assignee_user_id=spec["assignee_user"],
        assignee_role=spec["assignee_role"],
        entered_at=now,
        due_at=add_work_days(now, spec["due_work_days"], work_days),
    )


def _ruled(check, *args):
    try:
        return check(*args)
    except rules.RuleRefused as refused:
        raise WorkflowError(str(refused), code=refused.code) from refused


def submit(version: ProgramVersion, *, actor, role: str, reason: str = "") -> ProgramVersion:
    """Sends a draft for review: it becomes submitted, then enters its first stage, in one transaction (D52).

    The pre-submit check (task 5.4) runs on the version's rows under its lock, after the live editor handed over
    its latest content; what it keeps (the critical findings and the author's reason) goes with the submission."""
    if not can_edit(version.program, actor, role):
        raise NotAllowed("only the program's collaborators submit it")
    previous = _returned_from(version)
    if previous is not None:
        stages = previous.stages
        returned_at = previous.decisions.filter(decision=StageDecision.Decision.RETURN).last().stage
        start = 1 if stages[returned_at - 1]["resubmit"] == Resubmit.RESTART else returned_at
        template_id = previous.template_id
    else:
        template = template_for(version.program)
        stages = _snapshot(template) if template is not None else []
        if not stages:
            raise WorkflowError("choose an approval workflow first", code="no_workflow")
        start, template_id = 1, template.pk
    kept: dict = {}
    payload: dict = {"start_stage": start}

    def checks(locked: ProgramVersion) -> None:
        kept.update(_ruled(rules.pre_submit, locked, reason))
        if kept:
            payload["pre_submit"] = kept

    def enter(submitted: ProgramVersion) -> None:
        instance = WorkflowInstance.objects.create(
            version=submitted,
            template_id=template_id,
            stages=stages,
            previous=previous,
            start_stage=start,
            pre_submit=kept,
            submitted_by=actor,
        )
        lifecycle.transition(submitted, S.IN_STAGE, actor=actor, stage=start)
        _open_task(instance, start, timezone.now())

    # The payload is read when the transition is recorded, after the check filled it.
    lifecycle.transition(version, S.SUBMITTED, actor=actor, check=checks, then=enter, payload=payload)
    return ProgramVersion.objects.get(pk=version.pk)


def _lock(version: ProgramVersion) -> tuple[ProgramVersion, WorkflowInstance]:
    locked = ProgramVersion.objects.select_for_update(no_key=True).get(pk=version.pk)
    instance = WorkflowInstance.objects.select_for_update().filter(version=locked).first()
    if instance is None or instance.outcome:
        raise WorkflowError("this version is not under review", code="not_in_review")
    return locked, instance


def _lock_task(task: StageTask) -> tuple[ProgramVersion, WorkflowInstance, StageTask]:
    version_id = StageTask.objects.filter(pk=task.pk).values_list("instance__version_id", flat=True).get()
    version, instance = _lock(ProgramVersion(pk=version_id))
    task = StageTask.objects.select_for_update().get(pk=task.pk)
    if task.closed_at is not None:
        raise WorkflowError("this task is already decided", code="task_closed")
    return version, instance, task


def _close(instance: WorkflowInstance, outcome: str, now) -> None:
    instance.tasks.filter(closed_at__isnull=True).update(closed_at=now, outcome=outcome)
    instance.outcome, instance.closed_at = outcome, now
    instance.save(update_fields=["outcome", "closed_at"])


@transaction.atomic
def claim(task: StageTask, *, actor, role: str) -> StageTask:
    """A holder of the stage's role takes its task; from then on it is theirs alone (D57)."""
    _, _, task = _lock_task(task)
    if not task.assignee_role or role != task.assignee_role:
        raise WorkflowError("this task is not for your role", code="not_your_task")
    if task.claimed_by_id is not None:
        if task.claimed_by_id == actor.pk:
            return task
        raise WorkflowError("someone has already taken this task", code="task_claimed")
    task.claimed_by, task.claimed_at = actor, timezone.now()
    task.save(update_fields=["claimed_by", "claimed_at"])
    record("workflow.task_claimed", actor=actor, target=task.instance.version, payload={"task": task.pk})
    return task


@transaction.atomic
def release(task: StageTask, *, actor, role: str) -> StageTask:
    """The one who claimed a task, or an admin, gives it back to the role."""
    _, _, task = _lock_task(task)
    if task.claimed_by_id is None:
        return task
    if task.claimed_by_id != actor.pk and role != Role.ADMIN:
        raise NotAllowed("only who took the task or an admin can give it back")
    task.claimed_by, task.claimed_at = None, None
    task.save(update_fields=["claimed_by", "claimed_at"])
    record("workflow.task_released", actor=actor, target=task.instance.version, payload={"task": task.pk})
    return task


@transaction.atomic
def decide(task: StageTask, *, actor, role: str, decision: str, note: str = "") -> ProgramVersion:
    """Approve (the next stage, or final approval after the last) or return (a new draft for the authors), under
    the conditions on comments (task 5.5)."""
    version, instance, task = _lock_task(task)
    if task.assignee_role and task.claimed_by_id is None:
        raise WorkflowError("take the task before deciding", code="task_not_claimed")
    if task.responsible() != actor:
        raise WorkflowError("this task is someone else's", code="not_your_task")
    if decision not in StageDecision.Decision.values:
        raise WorkflowError("approve or return", code="decision_invalid")
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise WorkflowError("the note is too long", code="note_too_long")
    if decision == StageDecision.Decision.RETURN and not note:
        raise WorkflowError("say why the version is returned", code="return_note_required")
    _ruled(rules.decision, version, instance, task, decision)

    now = timezone.now()
    StageDecision.objects.create(
        instance=instance, task=task, stage=task.stage, user=actor, decision=decision, note=note
    )
    task.closed_at, task.outcome = now, decision
    task.save(update_fields=["closed_at", "outcome"])
    record(
        "workflow.decision",
        actor=actor,
        target=version,
        payload={"stage": task.stage, "decision": decision, "note": note, "task": task.pk},
    )
    payload = {"decision": decision, "task": task.pk}
    if decision == StageDecision.Decision.RETURN:
        _close(instance, WorkflowInstance.Outcome.RETURNED, now)
        return lifecycle.transition(version, S.RETURNED, actor=actor, payload=payload)
    if task.stage < len(instance.stages):
        version = lifecycle.transition(version, S.IN_STAGE, actor=actor, stage=task.stage + 1, payload=payload)
        _open_task(instance, task.stage + 1, now)
        return version
    _close(instance, WorkflowInstance.Outcome.APPROVED, now)
    return lifecycle.transition(version, S.APPROVED, actor=actor, payload=payload)


@transaction.atomic
def withdraw(version: ProgramVersion, *, actor, role: str) -> ProgramVersion:
    """The authors take a submission back before anyone decided on it (D56); they get a new draft."""
    version, instance = _lock(version)
    if not can_edit(version.program, actor, role):
        raise NotAllowed("only the program's collaborators withdraw it")
    if instance.decisions.exists():
        raise WorkflowError("a decision was taken on this submission", code="withdraw_after_decision")
    _close(instance, WorkflowInstance.Outcome.WITHDRAWN, timezone.now())
    return lifecycle.transition(version, S.WITHDRAWN, actor=actor)


def cancel(version: ProgramVersion, *, actor, role: str) -> ProgramVersion:
    """An admin stops a version for good before it is approved (D56)."""
    if role != Role.ADMIN:
        raise NotAllowed("only an admin cancels a version")
    if ProgramVersion.objects.filter(pk=version.pk, status=S.DRAFT).exists():
        # A draft has no submission; the live editor hands over its content before any lock (lifecycle).
        return lifecycle.transition(version, S.CANCELLED, actor=actor)
    with transaction.atomic():
        version = ProgramVersion.objects.select_for_update(no_key=True).get(pk=version.pk)
        instance = WorkflowInstance.objects.select_for_update().filter(version=version, outcome="").first()
        if instance is not None:
            _close(instance, WorkflowInstance.Outcome.CANCELLED, timezone.now())
        return lifecycle.transition(version, S.CANCELLED, actor=actor)
