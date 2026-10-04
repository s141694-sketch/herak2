"""The fixed automations of spec 6.4 (task 5.9) and the notifications they make (6.5, task 5.8): each starts from an
audit log entry, after its transaction committed, through a Celery task."""

import pytest
from django.core import mail

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.comments import services as comments
from apps.notifications import digest
from apps.notifications.models import EmailMode, Notification, NotificationPreference
from apps.programs import services as programs
from apps.programs.tests.factories import member, program
from apps.quality.models import QualityReport
from apps.tenancy.context import organization_context
from apps.workflows import deadlines, services
from apps.workflows.models import StageTask
from apps.workflows.tests.factories import two_stage_template

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        people = {
            "admin": member("admin@example.com", Role.ADMIN),
            "author": member("author@example.com", Role.AUTHOR),
            "reviewer": member("reviewer@example.com", Role.REVIEWER),
            "reviewer2": member("reviewer2@example.com", Role.REVIEWER),
            "approver": member("approver@example.com", Role.APPROVER),
        }
        two_stage_template(people["admin"], approver=people["approver"])
        version = program(people["author"], title="برنامج الإسعاف", targets=[]).versions.get()
        programs.add_node(version, title="الوحدة", actor=people["author"])
        yield {"org": org, "version": version, **people}


@pytest.fixture
def act(world, django_capture_on_commit_callbacks):
    """Runs an action in the organization with its commit callbacks (the dispatch) executed."""

    def run(action):
        with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
            return action()

    return run


def notes(world, event=None):
    with organization_context(world["org"]):
        found = Notification.objects.order_by("id")
        if event:
            found = found.filter(event=event)
        return [(n.recipient.email, n.event) for n in found]


def task_of(world):
    with organization_context(world["org"]):
        return StageTask.objects.get(instance__version__program=world["version"].program, closed_at__isnull=True)


def submit(world, act, version=None):
    return act(lambda: services.submit(version or world["version"], actor=world["author"], role=Role.AUTHOR))


def decide(world, act, user, decision, note=""):
    task = task_of(world)

    def run():
        if task.assignee_role:
            services.claim(task, actor=user, role=user.memberships.get().role)
        if decision == "return":
            version = task.instance.version
            comments.create_comment(
                program=version.program,
                version=version,
                author=user,
                body="أكمل",
                category="must_fix",
                node_key=version.nodes.first().node_key,
            )
        return services.decide(task, actor=user, role=user.memberships.get().role, decision=decision, note=note)

    return act(run)


def test_a_submission_is_analysed_and_the_first_stage_is_told(world, act):
    submit(world, act)
    with organization_context(world["org"]):
        assert QualityReport.objects.get(version=world["version"]).last_run == QualityReport.Run.FULL
    assert notes(world) == [
        ("reviewer@example.com", "task_assigned"),
        ("reviewer2@example.com", "task_assigned"),
    ]
    assert sorted(m.to[0] for m in mail.outbox) == ["reviewer2@example.com", "reviewer@example.com"]
    message = mail.outbox[0]
    assert "برنامج الإسعاف" in message.subject
    assert "مراجعة فنية" in message.body and "Review" in message.body  # Arabic, then English
    assert f"/program-versions/{world['version'].pk}" in message.body


def test_approving_a_stage_tells_the_next_one(world, act):
    submit(world, act)
    decide(world, act, world["reviewer"], "approve")
    assert notes(world)[-1] == ("approver@example.com", "task_assigned")


def test_a_return_tells_the_authors_with_the_note(world, act):
    submit(world, act)
    decide(world, act, world["reviewer"], "return", note="أكمل التقويم")
    assert notes(world, "version_returned") == [("author@example.com", "version_returned")]
    with organization_context(world["org"]):
        returned = Notification.objects.get(event="version_returned")
    assert returned.params["note"] == "أكمل التقويم"
    assert "أكمل التقويم" in mail.outbox[-1].body


def test_final_approval_tells_everyone_and_asks_for_the_export(world, act):
    submit(world, act)
    decide(world, act, world["reviewer"], "approve")
    decide(world, act, world["approver"], "approve")
    # The authors and every other person who decided; never the one who acted.
    assert sorted(notes(world, "version_approved")) == [
        ("author@example.com", "version_approved"),
        ("reviewer@example.com", "version_approved"),
    ]
    with organization_context(world["org"]):
        export = AuditLog.objects.get(event="program_version.export_requested")
    assert export.target_id == str(world["version"].pk)


def test_reminders_go_to_the_responsible_and_escalation_to_the_admins(world, act):
    from datetime import timedelta

    submit(world, act)
    task = task_of(world)
    act(lambda: services.claim(task, actor=world["reviewer"], role=Role.REVIEWER))
    act(lambda: deadlines.check(now=task.due_at + timedelta(days=30)))
    assert notes(world, "task_due") == [("reviewer@example.com", "task_due")]
    assert notes(world, "task_overdue") == [("admin@example.com", "task_overdue")]


def test_a_daily_digest_gathers_what_happened_once(world, act):
    with organization_context(world["org"]):
        for user in (world["reviewer"], world["reviewer2"]):
            NotificationPreference.objects.create(user=user, email=EmailMode.DAILY)
    submit(world, act)
    assert mail.outbox == []  # nothing immediate
    digest.send_all()
    assert sorted(m.to[0] for m in mail.outbox) == ["reviewer2@example.com", "reviewer@example.com"]
    assert "برنامج الإسعاف" in mail.outbox[0].body
    digest.send_all()
    assert len(mail.outbox) == 2  # each notification goes in one digest only


def test_in_platform_only_sends_no_email(world, act):
    with organization_context(world["org"]):
        for user in (world["reviewer"], world["reviewer2"]):
            NotificationPreference.objects.create(user=user, email=EmailMode.OFF)
    submit(world, act)
    digest.send_all()
    assert mail.outbox == [] and len(notes(world)) == 2


def test_a_dispatch_runs_once_per_entry(world, act):
    from apps.notifications.automation import dispatch

    submit(world, act)
    with organization_context(world["org"]):
        entry = AuditLog.objects.filter(event="program_version.transition", payload__to="in_stage").get()
    dispatch(entry.pk)
    assert len(notes(world)) == 2 and len(mail.outbox) == 2
