"""The approval workflow (spec 6.1-6.3, tasks 5.1-5.3): templates, the way of a submission through its stages,
claiming a role's task, decisions, withdrawal and cancellation."""

from datetime import timedelta

import pytest

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.core.errors import Conflict
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context
from apps.workflows import services
from apps.workflows.models import StageDecision, StageTask, WorkflowInstance
from apps.workflows.workdays import add_work_days

from .factories import two_stage_template

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


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
        template = two_stage_template(people["admin"], approver=people["approver"])
        version = program(people["author"]).versions.get()
        yield {"org": org, "template": template, "version": version, **people}


def role(user):
    return user.memberships.get().role


def submit(world, version=None, **kwargs):
    version = version or world["version"]
    return services.submit(version, actor=world["author"], role=Role.AUTHOR, **kwargs)


def open_task(version) -> StageTask:
    return StageTask.objects.get(instance__version=version, closed_at__isnull=True)


def claim_and_decide(world, user, decision, note="", version=None):
    task = open_task(version or world["version"])
    if task.assignee_role:
        services.claim(task, actor=user, role=role(user))
    return services.decide(task, actor=user, role=role(user), decision=decision, note=note)


def draft_of(version):
    return version.program.versions.get(status=S.DRAFT)


def test_a_submission_enters_the_first_stage_with_its_due_time(world):
    version = submit(world)
    assert (version.status, version.current_stage) == (S.IN_STAGE, 1)
    instance = WorkflowInstance.objects.get(version=version)
    assert [s["name"] for s in instance.stages] == ["مراجعة فنية", "اعتماد"]
    task = open_task(version)
    assert (task.stage, task.assignee_role, task.assignee_user) == (1, Role.REVIEWER, None)
    assert task.due_at == add_work_days(task.entered_at, 2, world["org"].work_days)
    events = [e.payload["to"] for e in AuditLog.objects.filter(event="program_version.transition")]
    assert events == [S.SUBMITTED, S.IN_STAGE]


def test_without_a_workflow_a_version_cannot_be_submitted(world):
    world["template"].delete()
    with pytest.raises(Conflict) as refused:
        submit(world)
    assert refused.value.get_codes() == "no_workflow"
    world["version"].refresh_from_db()
    assert world["version"].status == S.DRAFT


def test_a_program_follows_its_chosen_template(world):
    other = services.save_template(
        None,
        actor=world["admin"],
        name="مسار قصير",
        is_default=False,
        stages=[{"name": "اعتماد مباشر", "assignee_user": world["approver"].pk, "due_work_days": 1}],
    )
    services.choose_template(world["version"].program, other, actor=world["author"])
    submit(world)
    assert open_task(world["version"]).assignee_user == world["approver"]


def test_editing_a_template_does_not_change_a_review_in_progress(world):
    submit(world)
    services.save_template(
        world["template"],
        actor=world["admin"],
        name="مسار معدل",
        is_default=True,
        stages=[{"name": "مرحلة واحدة", "assignee_role": "admin", "due_work_days": 5}],
    )
    instance = WorkflowInstance.objects.get(version=world["version"])
    assert len(instance.stages) == 2 and instance.stages[0]["name"] == "مراجعة فنية"


def test_a_role_task_is_claimed_by_one_holder_who_alone_decides(world):
    submit(world)
    task = open_task(world["version"])
    with pytest.raises(Conflict) as unclaimed:
        services.decide(task, actor=world["reviewer"], role=Role.REVIEWER, decision="approve")
    assert unclaimed.value.get_codes() == "task_not_claimed"
    with pytest.raises(Conflict) as wrong_role:
        services.claim(task, actor=world["approver"], role=Role.APPROVER)
    assert wrong_role.value.get_codes() == "not_your_task"
    services.claim(task, actor=world["reviewer"], role=Role.REVIEWER)
    with pytest.raises(Conflict) as taken:
        services.claim(task, actor=world["reviewer2"], role=Role.REVIEWER)
    assert taken.value.get_codes() == "task_claimed"
    with pytest.raises(Conflict) as not_theirs:
        services.decide(task, actor=world["reviewer2"], role=Role.REVIEWER, decision="approve")
    assert not_theirs.value.get_codes() == "not_your_task"
    # The admin may release a claim; then another holder takes it.
    services.release(task, actor=world["admin"], role=Role.ADMIN)
    services.claim(task, actor=world["reviewer2"], role=Role.REVIEWER)
    version = services.decide(task, actor=world["reviewer2"], role=Role.REVIEWER, decision="approve")
    assert (version.status, version.current_stage) == (S.IN_STAGE, 2)


def test_approving_each_stage_leads_to_final_approval(world):
    submit(world)
    claim_and_decide(world, world["reviewer"], "approve")
    task = open_task(world["version"])
    assert (task.stage, task.assignee_user) == (2, world["approver"])
    version = claim_and_decide(world, world["approver"], "approve", note="معتمد")
    assert version.status == S.APPROVED and version.approved_by == world["approver"]
    instance = WorkflowInstance.objects.get(version=version)
    assert instance.outcome == "approved" and instance.closed_at is not None
    assert not StageTask.objects.filter(instance=instance, closed_at__isnull=True).exists()
    assert list(instance.decisions.values_list("stage", "decision")) == [(1, "approve"), (2, "approve")]


def test_a_return_needs_a_note_and_hands_back_a_new_draft(world):
    submit(world)
    claim_and_decide(world, world["reviewer"], "approve")
    with pytest.raises(Conflict) as no_note:
        claim_and_decide(world, world["approver"], "return", note="  ")
    assert no_note.value.get_codes() == "return_note_required"
    version = claim_and_decide(world, world["approver"], "return", note="أكمل التقويم")
    assert version.status == S.RETURNED
    assert WorkflowInstance.objects.get(version=version).outcome == "returned"
    assert draft_of(version).source_version == version


def test_a_resubmission_goes_back_to_the_stage_that_returned_it(world):
    submit(world)
    claim_and_decide(world, world["reviewer"], "approve")
    returned = claim_and_decide(world, world["approver"], "return", note="أكمل التقويم")
    # A template edited meanwhile does not change where this chain of versions goes.
    services.save_template(
        world["template"],
        actor=world["admin"],
        name="مسار معدل",
        is_default=True,
        stages=[{"name": "مرحلة واحدة", "assignee_role": "admin", "due_work_days": 5}],
    )
    second = submit(world, draft_of(returned))
    assert (second.status, second.current_stage) == (S.IN_STAGE, 2)
    instance = WorkflowInstance.objects.get(version=second)
    assert instance.previous.version == returned and instance.start_stage == 2
    assert open_task(second).assignee_user == world["approver"]


def test_a_stage_set_to_restart_sends_a_resubmission_to_the_first_stage(world):
    world["template"].delete()
    two_stage_template(world["admin"], approver=world["approver"], first_resubmit="restart")
    submit(world)
    returned = claim_and_decide(world, world["reviewer"], "return", note="ابدأ من جديد")
    assert submit(world, draft_of(returned)).current_stage == 1


def test_the_author_withdraws_only_before_any_decision(world):
    submit(world)
    withdrawn = services.withdraw(world["version"], actor=world["author"], role=Role.AUTHOR)
    assert withdrawn.status == S.WITHDRAWN
    assert WorkflowInstance.objects.get(version=withdrawn).outcome == "withdrawn"
    assert not StageTask.objects.filter(closed_at__isnull=True).exists()

    # A new submission after a withdrawal starts afresh, at the first stage.
    again = submit(world, draft_of(withdrawn))
    assert again.current_stage == 1 and WorkflowInstance.objects.get(version=again).previous is None
    claim_and_decide(world, world["reviewer"], "approve", version=again)
    with pytest.raises(Conflict) as late:
        services.withdraw(again, actor=world["author"], role=Role.AUTHOR)
    assert late.value.get_codes() == "withdraw_after_decision"


def test_only_a_collaborator_withdraws_and_only_an_admin_cancels(world):
    submit(world)
    with pytest.raises(Conflict) as stranger:
        services.withdraw(world["version"], actor=world["reviewer"], role=Role.REVIEWER)
    assert stranger.value.get_codes() == "permission_denied"
    with pytest.raises(Conflict) as not_admin:
        services.cancel(world["version"], actor=world["author"], role=Role.AUTHOR)
    assert not_admin.value.get_codes() == "permission_denied"
    cancelled = services.cancel(world["version"], actor=world["admin"], role=Role.ADMIN)
    assert cancelled.status == S.CANCELLED
    assert WorkflowInstance.objects.get(version=cancelled).outcome == "cancelled"
    assert not StageTask.objects.filter(closed_at__isnull=True).exists()


def test_a_decision_is_taken_once_on_the_open_task(world):
    submit(world)
    task = open_task(world["version"])
    services.claim(task, actor=world["reviewer"], role=Role.REVIEWER)
    services.decide(task, actor=world["reviewer"], role=Role.REVIEWER, decision="approve")
    with pytest.raises(Conflict) as closed:
        services.decide(task, actor=world["reviewer"], role=Role.REVIEWER, decision="approve")
    assert closed.value.get_codes() == "task_closed"
    assert StageDecision.objects.count() == 1


def test_each_decision_is_audited_with_its_note(world):
    submit(world)
    claim_and_decide(world, world["reviewer"], "approve", note="سليم")
    entry = AuditLog.objects.filter(event="workflow.decision").get()
    assert entry.actor == world["reviewer"]
    assert entry.payload == {"stage": 1, "decision": "approve", "note": "سليم", "task": open_task_id(world, 1)}


def open_task_id(world, stage):
    return StageTask.objects.get(instance__version=world["version"], stage=stage).pk


def test_templates_are_checked(world):
    def save(stages, **kwargs):
        with pytest.raises(Conflict) as refused:
            services.save_template(None, actor=world["admin"], name="x", stages=stages, **kwargs)
        return refused.value.get_codes()

    assert save([]) == "workflow_stages_required"
    assert save([{"name": "a", "assignee_role": "author", "due_work_days": 1}]) == "workflow_stage_invalid"
    assert save([{"name": "a", "due_work_days": 1}]) == "workflow_stage_invalid"
    both = {"name": "a", "assignee_role": "reviewer", "assignee_user": world["approver"].pk, "due_work_days": 1}
    assert save([both]) == "workflow_stage_invalid"
    pending = member("pending@example.com", Role.PENDING)
    assert save([{"name": "a", "assignee_user": pending.pk, "due_work_days": 1}]) == "workflow_stage_invalid"
    assert save([{"name": "", "assignee_role": "reviewer", "due_work_days": 1}]) == "workflow_stage_invalid"
    many = [{"name": f"s{i}", "assignee_role": "reviewer", "due_work_days": 1} for i in range(21)]
    assert save(many) == "workflow_stages_too_many"


def test_one_template_is_the_default(world):
    second = services.save_template(
        None,
        actor=world["admin"],
        name="ثان",
        is_default=True,
        stages=[{"name": "a", "assignee_role": "reviewer", "due_work_days": 1}],
    )
    world["template"].refresh_from_db()
    assert second.is_default and not world["template"].is_default


def test_a_template_chosen_by_a_program_cannot_be_deleted(world):
    services.choose_template(world["version"].program, world["template"], actor=world["author"])
    with pytest.raises(Conflict) as used:
        services.delete_template(world["template"], actor=world["admin"])
    assert used.value.get_codes() == "workflow_in_use"


def test_the_due_time_follows_the_work_days_of_the_organization(world):
    world["org"].work_days = [0, 1, 2, 3, 4, 5, 6]
    world["org"].save()
    submit(world)
    task = open_task(world["version"])
    assert task.due_at - task.entered_at == timedelta(days=2)
