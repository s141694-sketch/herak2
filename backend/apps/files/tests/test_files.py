"""Stored files (task 7.0; spec 3 storage, 4.6 File, 7.4): an S3-compatible store, kept per organization, and
handed out only through short signed links after the API checked who asks."""

import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.files import services
from apps.files.models import File
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "x" * 12


@pytest.fixture
def world(files_storage):
    org = Organization.objects.create(name="A", slug="a")
    other = Organization.objects.create(name="B", slug="b")
    with organization_context(org):
        admin = member("admin@a.test", Role.ADMIN)
        author = member("author@a.test", Role.AUTHOR)
        pending = member("pending@a.test", Role.PENDING)
    with organization_context(other):
        outsider = member("admin@b.test", Role.ADMIN)
    for user in (admin, author, pending, outsider):
        user.set_password(PASSWORD)
        user.save()
    return {"org": org, "other": other, "admin": admin, "author": author, "storage": files_storage}


def signed_in(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    return client


HELLO = "مرحبا".encode()


def stored(world, *, kind=File.Kind.EXPORT, actor="admin", data=HELLO):
    with organization_context(world["org"]):
        return services.store(
            data,
            name="برنامج السلامة.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            kind=kind,
            actor=world[actor],
        )


def test_a_stored_file_keeps_its_bytes_under_its_organization_with_a_fingerprint(world):
    data = b"PK\x03\x04 some docx bytes"
    file = stored(world, data=data)
    assert file.key.startswith(f"{world['org'].pk}/export/") and file.key.endswith(".docx")
    assert (file.size, file.sha256) == (len(data), hashlib.sha256(data).hexdigest())
    assert world["storage"].read(file.key) == data
    with organization_context(world["other"]):
        assert not File.objects.filter(pk=file.pk).exists()


def test_a_download_is_a_short_signed_link_given_after_the_api_checked_who_asks(world):
    file = stored(world)
    response = signed_in("author@a.test").get(f"/api/files/{file.pk}/download/")
    assert response.status_code == 302 and response["Cache-Control"] == "no-store"
    link = urlparse(response["Location"])
    query = parse_qs(link.query)
    assert query["X-Amz-Expires"] == ["60"] and "X-Amz-Signature" in query
    assert "attachment" in query["response-content-disposition"][0]
    assert requests.get(response["Location"], timeout=5).content == "مرحبا".encode()  # moto serves it


def test_nobody_outside_the_organization_or_not_yet_assigned_gets_a_link(world):
    file = stored(world)
    assert signed_in("admin@b.test").get(f"/api/files/{file.pk}/download/").status_code == 404
    assert signed_in("pending@a.test").get(f"/api/files/{file.pk}/download/").status_code in (403, 409)
    assert APIClient().get(f"/api/files/{file.pk}/download/").status_code in (401, 403, 409)


def test_an_uploaded_file_is_given_back_only_to_whoever_uploaded_it(world):
    file = stored(world, kind=File.Kind.UPLOAD, actor="author")
    assert signed_in("author@a.test").get(f"/api/files/{file.pk}/download/").status_code == 302
    assert signed_in("admin@a.test").get(f"/api/files/{file.pk}/download/").status_code == 404
