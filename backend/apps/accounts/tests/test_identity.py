"""The organization's visual identity (spec 4.1: logo and colors), which its exported files carry (spec 2.2, task
7.3): set by an admin; the logo kept in the file store (task 7.0)."""

import base64

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.files.models import File
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
# A 1x1 transparent PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        member("admin@a.test", Role.ADMIN)
        member("author@a.test", Role.AUTHOR)
    return {"org": org}


def signed_in(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


def test_an_admin_sets_the_primary_color(world):
    admin = signed_in("admin@a.test")
    assert (
        admin.patch("/api/organizations/current/identity/", {"primary_color": "#0b6e4f"}, format="json").status_code
        == 200
    )
    world["org"].refresh_from_db()
    assert world["org"].brand_colors == {"primary": "#0B6E4F"}
    assert admin.get("/api/organizations/current/identity/").json() == {"primary_color": "#0B6E4F", "logo": None}


@pytest.mark.parametrize("color", ["green", "#12345", "#GGGGGG", 5])
def test_a_color_is_six_hex_digits(world, color):
    response = signed_in("admin@a.test").patch(
        "/api/organizations/current/identity/", {"primary_color": color}, format="json"
    )
    assert response.status_code == 400


def test_an_admin_uploads_the_logo_which_members_can_see_and_removes_it(world):
    admin = signed_in("admin@a.test")
    uploaded = admin.post(
        "/api/organizations/current/identity/logo/", {"file": SimpleUploadedFile("logo.png", PNG)}, format="multipart"
    )
    assert uploaded.status_code == 200, uploaded.content
    logo = uploaded.json()["logo"]
    world["org"].refresh_from_db()
    assert world["org"].logo_file_id == logo["id"]
    assert signed_in("author@a.test").get(f"/api/files/{logo['id']}/download/").status_code == 302
    assert admin.delete("/api/organizations/current/identity/logo/").status_code == 200
    world["org"].refresh_from_db()
    assert world["org"].logo_file_id is None


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("logo.gif", b"GIF89a" + b"\0" * 20, "logo_type_unsupported"),
        ("logo.png", PNG + b"\0" * 1_100_000, "logo_too_large"),
    ],
)
def test_a_logo_is_a_png_or_jpeg_of_at_most_a_megabyte(world, name, data, code):
    response = signed_in("admin@a.test").post(
        "/api/organizations/current/identity/logo/", {"file": SimpleUploadedFile(name, data)}, format="multipart"
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == code
    with organization_context(world["org"]):
        assert not File.objects.exists()


def test_only_an_admin_changes_the_identity(world):
    author = signed_in("author@a.test")
    assert (
        author.patch("/api/organizations/current/identity/", {"primary_color": "#000000"}, format="json").status_code
        == 403
    )
    assert (
        author.post(
            "/api/organizations/current/identity/logo/", {"file": SimpleUploadedFile("l.png", PNG)}, format="multipart"
        ).status_code
        == 403
    )
    assert author.get("/api/organizations/current/identity/").status_code == 200
