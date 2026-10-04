"""The fixed automations of spec 6.4 (task 5.9).

Every event is written to the audit log first (apps.audit.services.record). For the events in ``HANDLED``, the
entry is handed to a Celery task once its transaction committed; the task derives the notifications (and, on
approval, the request for the export) from the entry alone, so handling it again changes nothing.

| Event                     | What follows                                                     |
|---------------------------|------------------------------------------------------------------|
| draft turned into rows    | light analysis (apps.quality.receivers)                          |
| submission                | full analysis (apps.quality.receivers), then the first stage told |
| reviewer's decision       | the next stage told, or the authors when it was returned         |
| delay                     | reminder, then escalation (apps.workflows.deadlines)             |
| approval                  | the version is locked; export asked for (phase 7); everyone told |
"""

import sentry_sdk
import structlog
from celery import shared_task
from django.db import transaction
from django.dispatch import receiver

from apps.accounts.models import Membership, Role, User
from apps.audit.models import AuditLog
from apps.audit.services import record, recorded
from apps.programs.models import ProgramVersion
from apps.tenancy.context import organization_context
from apps.workflows.models import Reminder, StageDecision, StageTask, WorkflowInstance

from . import email
from .models import Notification

log = structlog.get_logger("harak2.notifications")
S = ProgramVersion.Status
E = Notification.Event
HANDLED = {"program_version.transition", "workflow.reminder"}


@receiver(recorded)
def on_recorded(sender, entry: AuditLog, **kwargs):
    if entry.event not in HANDLED:
        return
    entry_id = entry.pk

    def enqueue():
        try:
            dispatch.apply_async((entry_id,), retry=False)
        except Exception as exc:  # the broker being down must not fail what was already committed
            log.error("notifications.enqueue_failed", entry=entry_id, error=str(exc))
            sentry_sdk.capture_exception(exc)

    transaction.on_commit(enqueue)


@shared_task(name="notifications.dispatch", ignore_result=True)
def dispatch(entry_id: int) -> None:
    entry = AuditLog.all_organizations.get(pk=entry_id)
    with organization_context(entry.organization_id):
        version = ProgramVersion.objects.select_related("program").get(pk=int(entry.target_id))
        made = _handle(entry, version)
    email.send_now(made)


def _handle(entry: AuditLog, version: ProgramVersion) -> list[Notification]:
    if entry.event == "workflow.reminder":
        return _reminder(entry, version)
    target = entry.payload.get("to")
    if target == S.IN_STAGE:
        task = StageTask.objects.filter(instance__version=version, stage=entry.payload.get("stage")).last()
        return _notify(entry, version, E.TASK_ASSIGNED, _responsible(task), task=task)
    if target == S.RETURNED:
        decision = _decision(entry)
        params = {"note": decision.note if decision else ""}
        task = decision.task if decision else None
        return _notify(entry, version, E.VERSION_RETURNED, _authors(version), task=task, extra=params)
    if target == S.APPROVED:
        if not AuditLog.objects.filter(event="program_version.export_requested", target_id=str(version.pk)).exists():
            # Word and PDF are made in phase 7 (D60); the request is on record from now.
            record("program_version.export_requested", target=version, payload={"formats": ["docx", "pdf"]})
        instance = WorkflowInstance.objects.filter(version=version).first()
        deciders = User.objects.filter(pk__in=instance.decisions.values("user")) if instance else User.objects.none()
        people = {u.pk: u for u in [*_authors(version), *deciders]}
        return _notify(entry, version, E.VERSION_APPROVED, list(people.values()))
    return []


def _reminder(entry: AuditLog, version: ProgramVersion) -> list[Notification]:
    task = StageTask.objects.select_related("instance", "claimed_by", "assignee_user").get(pk=entry.payload["task"])
    if task.closed_at is not None:
        return []  # decided between the reminder and its handling
    kind = entry.payload["kind"]
    if kind == Reminder.Kind.ESCALATION:
        admins = User.objects.filter(memberships__role=Role.ADMIN, memberships__organization_id=entry.organization_id)
        responsible = ", ".join(u.full_name or u.email for u in _responsible(task))
        return _notify(entry, version, E.TASK_OVERDUE, list(admins), task=task, extra={"responsible": responsible})
    event = E.TASK_DUE_SOON if kind == Reminder.Kind.BEFORE_DUE else E.TASK_DUE
    return _notify(entry, version, event, _responsible(task), task=task)


def _decision(entry: AuditLog) -> StageDecision | None:
    task_id = entry.payload.get("task")
    return StageDecision.objects.filter(task_id=task_id).select_related("task").first() if task_id else None


def _responsible(task: StageTask | None) -> list[User]:
    """Who has to act on a task: the person it names or who claimed it, else every holder of its role."""
    if task is None:
        return []
    if task.responsible() is not None:
        return [task.responsible()]
    return list(User.objects.filter(pk__in=Membership.objects.filter(role=task.assignee_role).values("user")))


def _authors(version: ProgramVersion) -> list[User]:
    return list(User.objects.filter(pk__in=version.program.collaborators.values("user")))


def _notify(entry, version, event, people, *, task=None, extra=None) -> list[Notification]:
    instance = task.instance if task is not None else WorkflowInstance.objects.filter(version=version).first()
    params = {
        "program": version.program.title,
        "program_id": version.program_id,
        "number": version.number,
        "stage": task.stage if task else None,
        "stage_name": instance.stages[task.stage - 1]["name"] if task and instance else "",
        "due_at": task.due_at.isoformat() if task else None,
        "task": task.pk if task else None,
        **(extra or {}),
    }
    made = []
    for person in people:
        if entry.actor_id is not None and person.pk == entry.actor_id:
            continue  # nobody is told of what they did themselves
        notification, created = Notification.objects.get_or_create(
            audit_entry=entry.pk, recipient=person, event=event, defaults={"version": version, "params": params}
        )
        if created:
            made.append(notification)
    return made
