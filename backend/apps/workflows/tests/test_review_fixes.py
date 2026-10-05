"""Findings of the independent review of phase 5 (workflows), each reproduced here before it was fixed."""

import pytest
from django.dispatch import receiver
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role
from apps.comments import services as comments
from apps.core.errors import Conflict
from apps.programs import lifecycle
from apps.programs import services as programs
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context
from apps.workflows import services
from apps.workflows.models import StageTask, WorkflowInstance
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
            "approver": member("approver@example.com", Role.APPROVER),
        }
        for user in people.values():
            user.set_password("x" * 12)
            user.save()
        template = two_stage_template(people["admin"], approver=people["approver"])
        version = program(people["author"], targets=[]).versions.get()
        programs.add_node(version, title="الوحدة", actor=people["author"])
        yield {"org": org, "template": template, "version": version, **people}


def submit(world, version=None):
    return services.submit(version or world["version"], actor=world["author"], role=Role.AUTHOR)


def decide(world, user, decision, version=None):
    version = version or world["version"]
    task = StageTask.objects.get(instance__version=version, closed_at__isnull=True)
    role = Membership.objects.get(user=user).role
    if task.assignee_role:
        services.claim(task, actor=user, role=role)
    if decision == "return":
        comments.create_comment(
            program=version.program,
            version=version,
            author=user,
            body="أكمل",
            category="must_fix",
            node_key=version.nodes.first().node_key,
        )
    return services.decide(task, actor=user, role=role, decision=decision, note="ملاحظة")


def draft_of(version):
    return version.program.versions.get(status=S.DRAFT)


def test_a_cancel_that_meets_a_submission_closes_the_review_it_meets(world):
    """The admin cancels a draft while its author submits it: the cancellation must close the submission too."""
    fired = []

    @receiver(lifecycle.leaving_draft, weak=False)
    def author_submits_meanwhile(sender, version, target, **kwargs):
        if target == S.CANCELLED and not fired:
            fired.append(True)
            submit(world)

    try:
        cancelled = services.cancel(world["version"], actor=world["admin"], role=Role.ADMIN)
    finally:
        lifecycle.leaving_draft.disconnect(author_submits_meanwhile)
    assert fired and cancelled.status == S.CANCELLED
    assert WorkflowInstance.objects.get(version=cancelled).outcome == "cancelled"
    assert not StageTask.objects.filter(closed_at__isnull=True).exists()


def test_bad_input_is_refused_not_a_server_error(world):
    admin = APIClient()
    admin.post("/api/auth/login/", {"email": "admin@example.com", "password": "x" * 12}, format="json")
    stages = [{"name": "s", "assignee_role": "reviewer", "due_work_days": 1}]
    program_id = world["version"].program_id
    for template in ("abc", [1], True):
        response = admin.put(f"/api/programs/{program_id}/workflow/", {"template": template}, format="json")
        assert response.status_code == 400, template
    assert admin.post("/api/workflow-templates/", {"name": 123, "stages": stages}, format="json").status_code == 400
    body = {"name": "x", "stages": stages, "is_default": "false"}
    assert admin.post("/api/workflow-templates/", body, format="json").status_code == 400


@pytest.mark.parametrize("name", ["سطر\nآخر", "tab\there", "\x07"])
def test_names_with_control_characters_are_refused(world, name):
    with pytest.raises(Conflict) as refused:
        services.save_template(
            None,
            actor=world["admin"],
            name="x",
            stages=[{"name": name, "assignee_role": "reviewer", "due_work_days": 1}],
        )
    assert refused.value.get_codes() == "workflow_stage_invalid"
    with pytest.raises(Conflict) as refused:
        services.save_template(
            None,
            actor=world["admin"],
            name=name,
            stages=[{"name": "s", "assignee_role": "reviewer", "due_work_days": 1}],
        )
    assert refused.value.get_codes() == "workflow_name_invalid"


def test_a_withdrawn_resubmission_still_answers_the_return(world):
    submit(world)
    decide(world, world["reviewer"], "approve")
    returned = decide(world, world["approver"], "return")  # returned at stage 2
    second = submit(world, draft_of(returned))
    assert second.current_stage == 2
    withdrawn = services.withdraw(second, actor=world["author"], role=Role.AUTHOR)
    third = submit(world, draft_of(withdrawn))
    assert third.current_stage == 2  # D54: back to the stage that returned it
    instance = WorkflowInstance.objects.get(version=third)
    assert instance.previous.version == returned


def test_a_stage_person_must_be_able_to_review(world):
    with pytest.raises(Conflict) as refused:
        services.save_template(
            None,
            actor=world["admin"],
            name="x",
            stages=[{"name": "s", "assignee_user": world["author"].pk, "due_work_days": 1}],
        )
    assert refused.value.get_codes() == "workflow_stage_invalid"


def test_a_decider_whose_role_changed_no_longer_decides(world):
    submit(world)
    task = StageTask.objects.get(closed_at__isnull=True)
    services.claim(task, actor=world["reviewer"], role=Role.REVIEWER)
    # The reviewer became an author after taking the task.
    with pytest.raises(Conflict) as refused:
        services.decide(task, actor=world["reviewer"], role=Role.AUTHOR, decision="approve")
    assert refused.value.get_codes() == "not_your_task"


def test_invalid_work_days_are_refused_not_looped_on(world):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    with pytest.raises(ValueError):
        add_work_days(datetime(2026, 10, 4, tzinfo=ZoneInfo("Asia/Muscat")), 1, [7])
    world["org"].work_days = [7]
    world["org"].save()
    with pytest.raises(Conflict) as refused:
        submit(world)
    assert refused.value.get_codes() == "work_days_invalid"
    world["version"].refresh_from_db()
    assert world["version"].status == S.DRAFT
