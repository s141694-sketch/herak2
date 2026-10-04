"""Reminders and escalation in simulated time (spec 6.3, task 5.7): a reminder one work day before the due time,
another at it, then an escalation to the admins after the organization's delay; each once, and none once the
task is closed."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context
from apps.workflows import deadlines, services
from apps.workflows.models import Reminder, StageTask

from .factories import one_stage_template

pytestmark = pytest.mark.django_db
MUSCAT = ZoneInfo("Asia/Muscat")


def at(day, hour=10):
    # October 2026: the 4th is a Sunday; Friday and Saturday are days off.
    return datetime(2026, 10, day, hour, tzinfo=MUSCAT)


@pytest.fixture
def world(monkeypatch):
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        admin = member("admin@example.com", Role.ADMIN)
        author = member("author@example.com", Role.AUTHOR)
        member("reviewer@example.com", Role.REVIEWER)
        one_stage_template(admin, due_work_days=3)
        version = program(author, targets=[]).versions.get()
        # Entered on Sunday the 4th at 10:00: due Wednesday the 7th at 10:00.
        monkeypatch.setattr("django.utils.timezone.now", lambda: at(4))
        services.submit(version, actor=author, role=Role.AUTHOR)
        monkeypatch.undo()
        task = StageTask.objects.get(instance__version=version)
    assert task.due_at == at(7)
    return {"org": org, "task": task, "admin": admin}


def fired(org):
    with organization_context(org):
        return [
            (e.payload["kind"], e.payload["task"])
            for e in AuditLog.objects.filter(event="workflow.reminder").order_by("id")
        ]


def test_reminder_then_due_then_escalation_each_once(world):
    task_id = world["task"].pk
    deadlines.check(now=at(5, 9))  # Monday 09:00: nothing yet
    assert fired(world["org"]) == []
    deadlines.check(now=at(6, 10))  # Tuesday 10:00: one work day before the due time
    deadlines.check(now=at(6, 15))
    assert fired(world["org"]) == [("before_due", task_id)]
    deadlines.check(now=at(7, 10))  # Wednesday 10:00: due
    assert fired(world["org"])[-1] == ("at_due", task_id)
    deadlines.check(now=at(8, 10))  # Thursday: one work day late, not yet escalated (default: two)
    assert len(fired(world["org"])) == 2
    deadlines.check(now=at(11, 10))  # Sunday: two work days late (Friday and Saturday do not count)
    deadlines.check(now=at(12, 10))
    assert fired(world["org"]) == [("before_due", task_id), ("at_due", task_id), ("escalation", task_id)]


def test_a_late_first_look_sends_only_what_is_due_now(world):
    deadlines.check(now=at(7, 11))  # the beat was down until after the due time: no "due tomorrow" message
    assert [kind for kind, _ in fired(world["org"])] == ["at_due"]
    with organization_context(world["org"]):
        assert set(Reminder.objects.values_list("kind", "skipped")) == {("before_due", True), ("at_due", False)}


def test_a_closed_task_is_not_reminded(world):
    with organization_context(world["org"]):
        services.cancel(world["task"].instance.version, actor=world["admin"], role=Role.ADMIN)
    deadlines.check(now=at(20))
    assert fired(world["org"]) == []


def test_the_organization_sets_the_lead_and_the_delay(world):
    world["org"].reminder_before_due_work_days = 2
    world["org"].escalation_delay_work_days = 0
    world["org"].save()
    deadlines.check(now=at(5, 10))  # two work days before Wednesday
    assert [kind for kind, _ in fired(world["org"])] == ["before_due"]
    deadlines.check(now=at(7, 10))  # due, and escalated at once
    assert [kind for kind, _ in fired(world["org"])] == ["before_due", "at_due", "escalation"]


def test_a_lead_longer_than_the_time_allowed_sends_no_early_reminder(world):
    world["org"].reminder_before_due_work_days = 5
    world["org"].save()
    deadlines.check(now=at(5, 10))
    assert fired(world["org"]) == []
