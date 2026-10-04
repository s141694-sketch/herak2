"""Reminders and escalation (spec 6.3, task 5.7), run by Celery Beat.

For each open task: a reminder the organization's lead of work days before the due time, another at the due
time, then an escalation to the admins after the organization's delay in work days. Each is recorded once as a
Reminder and written to the audit log as ``workflow.reminder``; the notifications follow from that entry (6.4).
"""

from datetime import datetime

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Organization
from apps.audit.services import record
from apps.tenancy.context import organization_context

from .models import Reminder, StageTask
from .workdays import add_work_days, subtract_work_days

log = structlog.get_logger("harak2.workflows")
K = Reminder.Kind


def moments(task: StageTask, organization: Organization) -> dict[str, datetime | None]:
    work_days = organization.work_days
    before = subtract_work_days(task.due_at, organization.reminder_before_due_work_days, work_days)
    return {
        # No early reminder when the time allowed is shorter than the lead, or the lead is zero.
        K.BEFORE_DUE: before if task.entered_at < before < task.due_at else None,
        K.AT_DUE: task.due_at,
        K.ESCALATION: add_work_days(task.due_at, organization.escalation_delay_work_days, work_days),
    }


def _send(task: StageTask, kind: str, now: datetime, *, skipped: bool = False) -> bool:
    try:
        with transaction.atomic():
            Reminder.objects.create(task=task, kind=kind, skipped=skipped, sent_at=now)
            if not skipped:
                record(
                    "workflow.reminder",
                    target=task.instance.version,
                    payload={"kind": kind, "task": task.pk, "stage": task.stage, "due_at": task.due_at.isoformat()},
                )
    except IntegrityError:
        return False  # another run sent it first
    return True


def check_task(task: StageTask, organization: Organization, now: datetime) -> None:
    sent = set(task.reminders.values_list("kind", flat=True))
    times = moments(task, organization)
    if now >= times[K.AT_DUE]:
        if K.BEFORE_DUE not in sent and times[K.BEFORE_DUE] is not None:
            _send(task, K.BEFORE_DUE, now, skipped=True)  # too late to say "due soon"
        if K.AT_DUE not in sent:
            _send(task, K.AT_DUE, now)
    elif times[K.BEFORE_DUE] is not None and now >= times[K.BEFORE_DUE] and K.BEFORE_DUE not in sent:
        _send(task, K.BEFORE_DUE, now)
    if now >= times[K.ESCALATION] and K.ESCALATION not in sent:
        _send(task, K.ESCALATION, now)


def check(now: datetime | None = None) -> None:
    """Every organization's open tasks; ``now`` is given in tests to move through simulated time."""
    now = now or timezone.now()
    for organization in Organization.objects.all():
        with organization_context(organization):
            tasks = StageTask.objects.filter(closed_at__isnull=True).select_related("instance__version")
            for task in tasks:
                try:
                    check_task(task, organization, now)
                except Exception as exc:  # one broken task must not stop the others' reminders
                    log.error("workflows.deadline_check_failed", task=task.pk, error=str(exc))
