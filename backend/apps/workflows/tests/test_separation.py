"""Separation of duties (D91, the owner's decision of 2026-10-08): who edits a program does not decide on it. An
editor does not take a stage's task on it nor decide one, and a workflow whose stage names an editor is refused at
submission. A stage given to a role is taken by whoever holds the role and does not edit the program."""

import pytest

from apps.accounts.models import Membership, Organization, Role
from apps.core.errors import Conflict
from apps.programs import services as programs
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context
from apps.workflows import services
from apps.workflows.models import StageTask

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        people = {
            "writer": member("writer@example.com", Role.ADMIN),  # writes the program, and is an admin
            "other_admin": member("other@example.com", Role.ADMIN),
            "author": member("author@example.com", Role.AUTHOR),
            "reviewer": member("reviewer@example.com", Role.REVIEWER),
        }
        version = program(people["writer"], targets=[]).versions.get()
        programs.add_node(version, title="الوحدة", actor=people["writer"])
        programs.add_collaborator(version.program, people["author"], actor=people["writer"])
        yield {"org": org, "version": version, **people}


def workflow(world, stages):
    return services.save_template(None, actor=world["other_admin"], name="مسار", is_default=True, stages=stages)


def submit(world):
    return services.submit(world["version"], actor=world["author"], role=Role.AUTHOR)


def task(world) -> StageTask:
    return StageTask.objects.get(instance__version=world["version"], closed_at__isnull=True)


def refused(call) -> str:
    with pytest.raises(Conflict) as caught:
        call()
    return caught.value.detail.code


def test_an_editor_does_not_take_a_task_on_the_program_and_someone_else_does(world):
    workflow(world, [{"name": "اعتماد", "assignee_role": "admin", "due_work_days": 1}])
    submit(world)
    assert (
        refused(lambda: services.claim(task(world), actor=world["writer"], role=Role.ADMIN)) == "editor_cannot_decide"
    )
    services.claim(task(world), actor=world["other_admin"], role=Role.ADMIN)
    version = services.decide(task(world), actor=world["other_admin"], role=Role.ADMIN, decision="approve")
    assert version.status == "approved"


def test_an_author_who_became_a_reviewer_does_not_review_what_they_wrote(world):
    workflow(world, [{"name": "مراجعة", "assignee_role": "reviewer", "due_work_days": 1}])
    submit(world)
    Membership.objects.filter(user=world["author"]).update(role=Role.REVIEWER)
    assert refused(lambda: services.claim(task(world), actor=world["author"], role=Role.REVIEWER)) == (
        "editor_cannot_decide"
    )
    services.claim(task(world), actor=world["reviewer"], role=Role.REVIEWER)


def test_a_workflow_that_names_an_editor_is_refused_at_submission(world):
    workflow(world, [{"name": "اعتماد", "assignee_user": world["writer"].pk, "due_work_days": 1}])
    assert refused(lambda: submit(world)) == "stage_names_an_editor"
    assert world["version"].__class__.objects.get(pk=world["version"].pk).status == "draft"


def test_one_who_took_a_task_and_then_became_an_editor_does_not_decide(world):
    workflow(world, [{"name": "اعتماد", "assignee_role": "admin", "due_work_days": 1}])
    submit(world)
    services.claim(task(world), actor=world["other_admin"], role=Role.ADMIN)
    programs.add_collaborator(world["version"].program, world["other_admin"], actor=world["writer"])
    decide = lambda: services.decide(task(world), actor=world["other_admin"], role=Role.ADMIN, decision="approve")  # noqa: E731
    assert refused(decide) == "editor_cannot_decide"
