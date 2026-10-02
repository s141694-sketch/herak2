import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.tenancy.context import organization_context

from .factories import member, published_framework, published_template

pytestmark = pytest.mark.django_db


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        admin = member("admin@example.com", Role.ADMIN)
        member("author@example.com", Role.AUTHOR)
        member("other@example.com", Role.AUTHOR)
        member("reviewer@example.com", Role.REVIEWER)
        template = published_template(admin)
        framework = published_framework(admin)
        competency_ids = list(framework.competencies.values_list("pk", flat=True))
    return {"template": template, "framework": framework, "competencies": competency_ids}


def create(client, world, **extra):
    body = {
        "title": "برنامج السلامة",
        "target_role": "فني",
        "template_version": world["template"].pk,
        "framework_version": world["framework"].pk,
        "targets": world["competencies"][:2],
        **extra,
    }
    return client.post("/api/programs/", body, format="json")


def test_author_creates_and_submits_and_withdraws_a_program(world):
    author = login("author@example.com")
    response = create(author, world)
    assert response.status_code == 201, response.content
    program = response.json()
    assert program["status"] == "draft"
    assert program["owner"]["email"] == "author@example.com"
    version_id = program["versions"][0]["id"]

    version = author.get(f"/api/program-versions/{version_id}/").json()
    assert version["status"] == "draft" and version["number"] == 1
    assert sorted(t["id"] for t in version["targets"]) == sorted(world["competencies"][:2])
    assert version["template"]["levels"][1]["name_en"] == "Module"

    assert (
        author.put(f"/api/program-versions/{version_id}/targets/", world["competencies"], format="json").status_code
        == 200
    )
    assert author.post(f"/api/program-versions/{version_id}/submit/").json()["status"] == "submitted"
    locked = author.put(f"/api/program-versions/{version_id}/targets/", [], format="json")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "version_locked"

    assert author.post(f"/api/program-versions/{version_id}/withdraw/").json()["status"] == "withdrawn"
    versions = author.get(f"/api/programs/{program['id']}/versions/").json()
    assert [(v["number"], v["status"]) for v in versions] == [(1, "withdrawn"), (2, "draft")]


def test_editing_requires_collaboration(world):
    author = login("author@example.com")
    program = create(author, world).json()
    version_id = program["versions"][0]["id"]
    other = login("other@example.com")
    reviewer = login("reviewer@example.com")
    assert other.get(f"/api/program-versions/{version_id}/").status_code == 200
    assert other.put(f"/api/program-versions/{version_id}/targets/", [], format="json").status_code == 403
    assert reviewer.post(f"/api/program-versions/{version_id}/submit/").status_code == 403
    assert reviewer.post("/api/programs/", {}, format="json").status_code == 403

    added = author.post(
        f"/api/programs/{program['id']}/collaborators/", {"user_email": "other@example.com"}, format="json"
    )
    assert added.status_code == 201, added.content
    assert other.put(f"/api/program-versions/{version_id}/targets/", [], format="json").status_code == 200
    collaborators = author.get(f"/api/programs/{program['id']}/collaborators/").json()
    assert sorted(c["user"]["email"] for c in collaborators) == ["author@example.com", "other@example.com"]
    removable = next(c for c in collaborators if c["user"]["email"] == "other@example.com")
    assert other.delete(f"/api/program-collaborators/{removable['id']}/").status_code == 403
    assert author.delete(f"/api/program-collaborators/{removable['id']}/").status_code == 204
    owner_entry = next(c for c in collaborators if c["user"]["email"] == "author@example.com")
    assert (
        author.delete(f"/api/program-collaborators/{owner_entry['id']}/").json()["error"]["code"]
        == "owner_is_collaborator"
    )


def test_creating_with_an_unpublished_template_is_a_clear_error(world):
    admin = login("admin@example.com")
    template = admin.post(
        "/api/structure-templates/", {"name": "t", "levels": [{"name_ar": "أ", "name_en": "A"}]}, format="json"
    ).json()
    response = create(admin, world, template_version=template["versions"][0]["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "template_not_published"
