import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


def client_for(org, role):
    user = User.objects.create_user(email=f"{role}-{org.slug}@example.com", password="x" * 12)
    with organization_context(org):
        Membership.objects.create(user=user, role=role)
    client = APIClient()
    client.post("/api/auth/login/", {"email": user.email, "password": "x" * 12}, format="json")
    return client


@pytest.fixture
def org():
    return Organization.objects.create(name="A", slug="a")


def test_admin_manages_a_framework_end_to_end(org):
    admin = client_for(org, Role.ADMIN)
    framework = admin.post("/api/competency-frameworks/", {"name": "إطار السلامة"}, format="json").json()
    assert framework["name"] == "إطار السلامة"
    version_id = framework["versions"][0]["id"]
    assert framework["versions"][0]["status"] == "draft"

    created = admin.post(
        f"/api/framework-versions/{version_id}/competencies/",
        {"code": "SAF-01", "title": "يحدد المخاطر", "level": "2", "requirement": "required"},
        format="json",
    )
    assert created.status_code == 201, created.content
    competency_id = created.json()["id"]
    renamed = admin.patch(f"/api/competencies/{competency_id}/", {"title": "يحدد المخاطر بدقة"}, format="json")
    assert renamed.status_code == 200

    competencies_url = f"/api/framework-versions/{version_id}/competencies/"
    duplicate = admin.post(competencies_url, {"code": "SAF-01", "title": "x"}, format="json")
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "validation_error"

    assert admin.post(f"/api/framework-versions/{version_id}/publish/").status_code == 200
    locked = admin.patch(f"/api/competencies/{competency_id}/", {"title": "x"}, format="json")
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "version_locked"

    new = admin.post(f"/api/competency-frameworks/{framework['id']}/versions/")
    assert new.status_code == 201
    assert new.json()["number"] == 2
    detail = admin.get(f"/api/framework-versions/{new.json()['id']}/").json()
    assert [c["code"] for c in detail["competencies"]] == ["SAF-01"]


def test_non_admins_can_read_but_not_write(org):
    admin = client_for(org, Role.ADMIN)
    author = client_for(org, Role.AUTHOR)
    framework = admin.post("/api/competency-frameworks/", {"name": "F"}, format="json").json()
    assert author.get("/api/competency-frameworks/").status_code == 200
    assert author.post("/api/competency-frameworks/", {"name": "G"}, format="json").status_code == 403
    version_id = framework["versions"][0]["id"]
    competencies_url = f"/api/framework-versions/{version_id}/competencies/"
    assert author.post(competencies_url, {"code": "X", "title": "x"}, format="json").status_code == 403
    assert author.post(f"/api/framework-versions/{version_id}/publish/").status_code == 403


def test_publishing_an_empty_version_is_a_clear_error(org):
    admin = client_for(org, Role.ADMIN)
    framework = admin.post("/api/competency-frameworks/", {"name": "F"}, format="json").json()
    response = admin.post(f"/api/framework-versions/{framework['versions'][0]['id']}/publish/")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "framework_empty"
