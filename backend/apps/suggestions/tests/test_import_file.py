"""Importing from a file (tasks 7.1, 7.2; spec 2.2, 7.7): the file is kept, its text comes back for the author to
check, and the existing import (preview, then the author's confirmation) takes it from there. A file that cannot be
read says why, and the author pastes the text instead."""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.files.models import File
from apps.files.tests.test_extraction import word
from apps.programs import lifecycle
from apps.programs.models import ProgramVersion
from apps.suggestions.models import Suggestion
from apps.tenancy.context import organization_context

from .test_suggestions import signed_in, world  # noqa: F401 - the world fixture

pytestmark = pytest.mark.django_db
FIXTURES = Path(__file__).resolve().parents[2] / "files" / "tests" / "fixtures"
LINES = (
    "الوحدة الأولى: السلامة في الورشة",
    "الدرس الأول: معدات الوقاية الشخصية",
    "الأهداف",
    "أن يحدد المتدرب معدات الوقاية الشخصية المناسبة لكل مهمة في الورشة.",
    "أن يطبق المتدرب إجراءات الإغلاق والتأمين قبل بدء أعمال الصيانة.",
)


def upload(client, version, data, name):
    return client.post(
        f"/api/program-versions/{version.pk}/import-file/",
        {"file": SimpleUploadedFile(name, data)},
        format="multipart",
    )


def test_a_word_file_is_kept_and_its_text_comes_back_for_the_author(world):  # noqa: F811
    response = upload(signed_in(), world["version"], word(*LINES), "منهج السلامة.docx")
    assert response.status_code == 200, response.content
    body = response.json()
    assert [line for line in body["text"].split("\n") if line][:5] == list(LINES)
    with organization_context(world["org"]):
        kept = File.objects.get(pk=body["file"]["id"])
    assert (kept.kind, kept.name, kept.created_by) == (File.Kind.UPLOAD, "منهج السلامة.docx", world["owner"])


def test_a_pdf_gives_its_text_and_the_import_records_which_file_it_came_from(world):  # noqa: F811
    client = signed_in()
    body = upload(client, world["version"], (FIXTURES / "curriculum.pdf").read_bytes(), "curriculum.pdf").json()
    assert "أن يحدد المتدرب معدات الوقاية" in body["text"]
    asked = client.post(
        f"/api/program-versions/{world['version'].pk}/suggestions/",
        {"kind": "import", "text": body["text"], "source_file": body["file"]["id"]},
        format="json",
    )
    assert asked.status_code == 202, asked.content
    with organization_context(world["org"]):
        assert Suggestion.objects.get(pk=asked.json()["id"]).request["source_file"] == body["file"]["id"]


def test_a_scanned_pdf_says_to_paste_the_text_and_keeps_nothing(world):  # noqa: F811
    response = upload(signed_in(), world["version"], (FIXTURES / "scanned.pdf").read_bytes(), "scan.pdf")
    assert response.status_code == 409 and response.json()["error"]["code"] == "file_no_text"
    with organization_context(world["org"]):
        assert not File.objects.exists()


@pytest.mark.parametrize(
    "fixture,code", [("encrypted.pdf", "file_encrypted"), (None, "file_type_unsupported"), ("", "file_required")]
)
def test_a_file_that_cannot_be_read_says_why(world, fixture, code):  # noqa: F811
    client = signed_in()
    if fixture == "":
        response = client.post(f"/api/program-versions/{world['version'].pk}/import-file/", {}, format="multipart")
    else:
        data = (FIXTURES / fixture).read_bytes() if fixture else b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64
        response = upload(client, world["version"], data, fixture or "old.doc")
    assert response.status_code in (400, 409) and response.json()["error"]["code"] == code


def test_only_the_programs_collaborators_upload_and_only_into_a_draft(world):  # noqa: F811
    data = word(*LINES)
    assert upload(signed_in("reviewer@example.com"), world["version"], data, "a.docx").status_code == 403
    with organization_context(world["org"]):
        lifecycle.transition(world["version"], ProgramVersion.Status.CANCELLED, actor=world["owner"])
    locked = upload(signed_in(), world["version"], data, "a.docx")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "version_locked"
    assert APIClient().post(f"/api/program-versions/{world['version'].pk}/import-file/").status_code in (401, 403, 409)


def test_an_import_cannot_name_a_file_someone_else_uploaded(world):  # noqa: F811
    from apps.files import services as files

    with organization_context(world["org"]):
        foreign = files.store(
            b"x", name="a.txt", content_type="text/plain", kind=File.Kind.UPLOAD, actor=world["reviewer"]
        )
    asked = signed_in().post(
        f"/api/program-versions/{world['version'].pk}/suggestions/",
        {"kind": "import", "text": "\n".join(LINES), "source_file": foreign.pk},
        format="json",
    )
    assert asked.status_code == 400
