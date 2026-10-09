"""Files kept on the server itself (D98, the owner's decision of 2026-10-09): FILES_BACKEND=local keeps them in a folder
(a compose volume) instead of an S3 bucket. The API still decides who may have a file; the link it then gives is
signed by Harak, lasts FILES_LINK_SECONDS, and names one file. Backups and restores work the same."""

import json
import time

import pytest
from django.core import signing
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.core import backup as backups
from apps.files import services, storage
from apps.files.models import File
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "x" * 12


@pytest.fixture
def local(settings, tmp_path):
    settings.FILES_BACKEND = "local"
    settings.FILES_LOCAL_DIR = str(tmp_path / "files")
    settings.FILES_LINK_SECONDS = 60
    return tmp_path / "files"


@pytest.fixture
def world(local):
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        author = member("author@a.test", Role.AUTHOR)
        other = member("other@a.test", Role.AUTHOR)
    for user in (author, other):
        user.set_password(PASSWORD)
        user.save()
    return {"org": org, "author": author, "dir": local}


def signed_in(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    return client


def stored(world, kind=File.Kind.EXPORT, data=b"PK word bytes", name="برنامج السلامة.docx"):
    with organization_context(world["org"]):
        return services.store(
            data, name=name, content_type="application/octet-stream", kind=kind, actor=world["author"]
        )


def test_a_file_is_written_read_listed_and_removed_in_the_folder(world):
    file = stored(world)
    assert (world["dir"] / file.key).read_bytes() == b"PK word bytes"
    assert storage.read(file.key) == b"PK word bytes"
    assert list(storage.keys()) == [file.key]
    storage.remove(file.key)
    assert list(storage.keys()) == []
    storage.remove(file.key)  # removing twice is not an error, as with S3


@pytest.mark.parametrize("key", ["../outside", "/etc/passwd", "a/../../b", ""])
def test_a_key_never_reaches_outside_the_folder(world, key):
    with pytest.raises(ValueError):
        storage.write(key, b"x", "text/plain")
    with pytest.raises(ValueError):
        storage.read(key)


def test_the_api_checks_access_then_its_signed_link_downloads_the_file_under_its_name(world):
    file = stored(world, kind=File.Kind.UPLOAD)
    refused = signed_in("other@a.test").get(f"/api/files/{file.pk}/download/")
    assert refused.status_code == 404  # an upload is its uploader's alone
    answer = signed_in("author@a.test").get(f"/api/files/{file.pk}/download/")
    assert answer.status_code == 302 and answer["Cache-Control"] == "no-store"
    link = answer["Location"]
    assert link.startswith("/api/files/content/")
    content = APIClient().get(link)  # the link itself is the permission, as an S3 signed link is
    assert content.status_code == 200
    assert b"".join(content.streaming_content) == b"PK word bytes"
    assert "attachment" in content["Content-Disposition"] and "utf-8''" in content["Content-Disposition"].lower()


def test_a_link_expires_and_a_changed_one_is_refused(world, settings):
    file = stored(world)
    link = storage.signed_link(file.key, name=file.name, content_type=file.content_type)
    token = link.rstrip("/").rsplit("/", 1)[1]
    forged = signing.dumps({"k": "../../etc/passwd", "n": "x", "t": "text/plain"}, salt="not-harak")
    assert APIClient().get(f"/api/files/content/{forged}/").status_code == 404
    assert APIClient().get(f"/api/files/content/{token[:-2]}xx/").status_code == 404
    settings.FILES_LINK_SECONDS = 1
    time.sleep(2)
    assert APIClient().get(link).status_code == 404


def test_a_link_to_a_removed_file_is_not_found(world):
    file = stored(world)
    link = storage.signed_link(file.key, name=file.name, content_type=file.content_type)
    storage.remove(file.key)
    assert APIClient().get(link).status_code == 404


def test_a_backup_holds_the_folders_files(world, tmp_path):
    file = stored(world, data=b"kept across a loss")
    folder = backups.backup(tmp_path / "backups")
    manifest = json.loads((folder / "manifest.json").read_text())
    assert [f["key"] for f in manifest["files"]] == [file.key]
    assert (folder / "files" / file.key).read_bytes() == b"kept across a loss"
