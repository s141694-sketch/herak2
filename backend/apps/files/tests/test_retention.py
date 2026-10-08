"""Files uploaded for an import are kept IMPORT_FILE_RETENTION_DAYS (30), then removed from the store and the
database (D93): their text is already in the import's request. Exports and logos are kept. A file the store could
not remove keeps its row, and is tried again the next day."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.files import services, storage
from apps.files.models import File
from apps.files.tasks import prune_uploads
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(files_storage, settings):
    settings.IMPORT_FILE_RETENTION_DAYS = 30
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        author = member("author@a.test", Role.AUTHOR)
    return {"org": org, "author": author}


def stored(world, kind, days_old):
    with organization_context(world["org"]):
        file = services.store(
            b"bytes", name="f.docx", content_type="application/octet-stream", kind=kind, actor=world["author"]
        )
    File.all_organizations.filter(pk=file.pk).update(created_at=timezone.now() - timedelta(days=days_old))
    return file


def test_an_upload_older_than_the_days_kept_is_removed_and_the_rest_stays(world):
    old, recent = stored(world, File.Kind.UPLOAD, 31), stored(world, File.Kind.UPLOAD, 29)
    export, logo = stored(world, File.Kind.EXPORT, 400), stored(world, File.Kind.LOGO, 400)
    prune_uploads()
    assert set(File.all_organizations.values_list("pk", flat=True)) == {recent.pk, export.pk, logo.pk}
    with pytest.raises(Exception):  # noqa: B017, PT011 - the store's own "no such key"
        storage.read(old.key)
    assert storage.read(recent.key) == b"bytes"
    [entry] = AuditLog.all_organizations.filter(event="file.expired")
    assert entry.organization_id == world["org"].pk and entry.payload["name"] == "f.docx"


def test_a_file_the_store_could_not_remove_keeps_its_row(world, monkeypatch):
    old = stored(world, File.Kind.UPLOAD, 31)

    def down(key):
        raise ConnectionError("the store is down")

    monkeypatch.setattr(storage, "remove", down)
    prune_uploads()
    assert File.all_organizations.filter(pk=old.pk).exists()
