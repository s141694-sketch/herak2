"""The workflow API (tasks 5.2, 5.3): templates for admins, submission, the reviewer's inbox and decisions."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "x" * 12


def login(email):
    client = APIClient()
    assert client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json").status_code == 200
    return client


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        people = {
            role: member(f"{role}@example.com", role)
            for role in (Role.ADMIN, Role.AUTHOR, Role.REVIEWER, Role.APPROVER)
        }
        for user in people.values():
            user.set_password(PASSWORD)
            user.save()
        version = program(people[Role.AUTHOR]).versions.get()
    return {"org": org, "version": version, **people}


STAGES = [
    {"name": "مراجعة", "assignee_role": "reviewer", "due_work_days": 2},
    {"name": "اعتماد", "assignee_role": "approver", "due_work_days": 1, "resubmit": "restart"},
]


def test_admins_write_templates_and_members_read_them(world):
    admin, author = login("admin@example.com"), login("author@example.com")
    assert author.post("/api/workflow-templates/", {"name": "x", "stages": STAGES}, format="json").status_code == 403
    created = admin.post(
        "/api/workflow-templates/", {"name": "المسار", "stages": STAGES, "is_default": True}, format="json"
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert [s["name"] for s in body["stages"]] == ["مراجعة", "اعتماد"] and body["stages"][1]["resubmit"] == "restart"
    assert author.get("/api/workflow-templates/").json()[0]["id"] == body["id"]
    bad = admin.put(f"/api/workflow-templates/{body['id']}/", {"name": "y", "stages": []}, format="json")
    assert (bad.status_code, bad.json()["error"]["code"]) == (409, "workflow_stages_required")
    assert admin.delete(f"/api/workflow-templates/{body['id']}/").status_code == 204


def test_a_version_goes_through_review_over_the_api(world):
    admin, author = login("admin@example.com"), login("author@example.com")
    reviewer, approver = login("reviewer@example.com"), login("approver@example.com")
    version_id = world["version"].pk
    refused = author.post(f"/api/program-versions/{version_id}/submit/")
    assert refused.json()["error"]["code"] == "no_workflow"
    admin.post("/api/workflow-templates/", {"name": "المسار", "stages": STAGES, "is_default": True}, format="json")
    assert reviewer.post(f"/api/program-versions/{version_id}/submit/").status_code == 403

    unexplained = author.post(f"/api/program-versions/{version_id}/submit/")
    assert unexplained.json()["error"]["code"] == "critical_findings_reason_required"
    submitted = author.post(f"/api/program-versions/{version_id}/submit/", {"reason": "سبب"}, format="json").json()
    assert (submitted["status"], submitted["current_stage"]) == ("in_stage", 1)
    [task] = reviewer.get("/api/tasks/").json()
    assert task["permissions"] == {"can_claim": True, "can_release": False, "can_decide": False}
    assert task["version"]["id"] == version_id and task["stage_name"] == "مراجعة"
    assert approver.get("/api/tasks/").json() == []
    assert reviewer.post(f"/api/tasks/{task['id']}/claim/").json()["permissions"]["can_decide"] is True
    decided = reviewer.post(f"/api/tasks/{task['id']}/decide/", {"decision": "approve"}, format="json").json()
    assert decided["current_stage"] == 2

    [final] = approver.get("/api/tasks/").json()
    approver.post(f"/api/tasks/{final['id']}/claim/")
    approved = approver.post(f"/api/tasks/{final['id']}/decide/", {"decision": "approve", "note": "تم"}, format="json")
    assert approved.json()["status"] == "approved"

    workflow = author.get(f"/api/program-versions/{version_id}/workflow/").json()["submission"]
    assert workflow["outcome"] == "approved"
    assert [(d["stage"], d["decision"], d["user"]["email"]) for d in workflow["decisions"]] == [
        (1, "approve", "reviewer@example.com"),
        (2, "approve", "approver@example.com"),
    ]


def test_a_version_never_submitted_has_no_workflow(world):
    assert login("author@example.com").get(f"/api/program-versions/{world['version'].pk}/workflow/").json() == {
        "submission": None,
        "returned": None,
    }


def test_a_program_chooses_its_template_while_it_has_a_draft(world):
    admin, author = login("admin@example.com"), login("author@example.com")
    first = admin.post("/api/workflow-templates/", {"name": "أ", "stages": STAGES, "is_default": True}, format="json")
    second = admin.post("/api/workflow-templates/", {"name": "ب", "stages": STAGES[:1]}, format="json").json()
    program_id = world["version"].program_id
    assert author.get(f"/api/programs/{program_id}/workflow/").json()["template"]["id"] == first.json()["id"]
    chosen = author.put(f"/api/programs/{program_id}/workflow/", {"template": second["id"]}, format="json").json()
    assert (chosen["chosen"], chosen["template"]["name"]) == (second["id"], "ب")
    assert (
        login("reviewer@example.com")
        .put(f"/api/programs/{program_id}/workflow/", {"template": None}, format="json")
        .status_code
        == 403
    )


def test_an_admin_cancels_and_follows_every_open_task(world):
    admin, author = login("admin@example.com"), login("author@example.com")
    admin.post("/api/workflow-templates/", {"name": "المسار", "stages": STAGES, "is_default": True}, format="json")
    version_id = world["version"].pk
    author.post(f"/api/program-versions/{version_id}/submit/", {"reason": "سبب"}, format="json")
    assert admin.get("/api/tasks/").json() == []
    assert len(admin.get("/api/tasks/?scope=all").json()) == 1
    assert author.post(f"/api/program-versions/{version_id}/cancel/").status_code == 403
    assert admin.post(f"/api/program-versions/{version_id}/cancel/").json()["status"] == "cancelled"
    assert admin.get("/api/tasks/?scope=all").json() == []


def test_a_draft_answering_a_return_shows_why_and_keeps_its_workflow(world):
    from apps.comments import services as comments
    from apps.programs import services as programs
    from apps.workflows.models import StageTask

    admin, author, reviewer = login("admin@example.com"), login("author@example.com"), login("reviewer@example.com")
    template = admin.post(
        "/api/workflow-templates/", {"name": "المسار", "stages": STAGES, "is_default": True}, format="json"
    ).json()
    other = admin.post("/api/workflow-templates/", {"name": "آخر", "stages": STAGES[:1]}, format="json").json()
    version = world["version"]
    with organization_context(world["org"]):
        node = programs.add_node(version, title="الوحدة", actor=world[Role.AUTHOR])
    author.post(f"/api/program-versions/{version.pk}/submit/", {"reason": "سبب"}, format="json")
    with organization_context(world["org"]):
        task = StageTask.objects.get(instance__version=version)
        comments.create_comment(
            program=version.program,
            version=version,
            author=world[Role.REVIEWER],
            body="أكمل",
            category="must_fix",
            node_key=node.node_key,
        )
    reviewer.post(f"/api/tasks/{task.pk}/claim/")
    reviewer.post(f"/api/tasks/{task.pk}/decide/", {"decision": "return", "note": "أكمل التقويم"}, format="json")
    with organization_context(world["org"]):
        draft = version.program.versions.get(status="draft")

    body = author.get(f"/api/program-versions/{draft.pk}/workflow/").json()
    assert body["submission"] is None
    assert body["returned"]["version"]["number"] == 1
    assert [(d["decision"], d["note"]) for d in body["returned"]["decisions"]] == [("return", "أكمل التقويم")]

    program_id = version.program_id
    chosen = author.get(f"/api/programs/{program_id}/workflow/").json()
    assert chosen["resubmission_of"] == 1 and chosen["template"]["id"] == template["id"]
    refused = author.put(f"/api/programs/{program_id}/workflow/", {"template": other["id"]}, format="json")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "workflow_fixed_by_return")


def test_an_admin_who_does_not_edit_the_program_chooses_its_workflow(world):
    admin = login("admin@example.com")
    template = admin.post("/api/workflow-templates/", {"name": "أ", "stages": STAGES}, format="json").json()
    program_id = world["version"].program_id
    chosen = admin.put(f"/api/programs/{program_id}/workflow/", {"template": template["id"]}, format="json").json()
    assert chosen["chosen"] == template["id"] and chosen["resubmission_of"] is None
