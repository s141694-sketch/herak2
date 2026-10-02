import io

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.competencies import services
from apps.competencies.models import Competency
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db

ARABIC_CSV = (
    "الرمز,العنوان,الوصف,المستوى,النوع\n"
    "SAF-01,يحدد مخاطر موقع العمل,وصف أول,2,إلزامية\n"
    "SAF-02,يستخدم معدات الوقاية,,1,اختيارية\n"
    ",,,,\n"
    "SAF-03,يبلّغ عن الحوادث،  فورًا,,3,\n"
)


@pytest.fixture
def setup():
    org = Organization.objects.create(name="A", slug="a")
    admin = User.objects.create_user(email="admin@example.com", password="x" * 12)
    with organization_context(org):
        Membership.objects.create(user=admin, role=Role.ADMIN)
        framework = services.create_framework(name="F", actor=admin)
        version = framework.versions.get()
    client = APIClient()
    client.post("/api/auth/login/", {"email": "admin@example.com", "password": "x" * 12}, format="json")
    return org, admin, version, client


def upload(client, version, name, content: bytes):
    file = SimpleUploadedFile(name, content)
    return client.post(f"/api/framework-versions/{version.pk}/imports/", {"file": file}, format="multipart")


def xlsx(rows) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_csv_with_arabic_headers_previews_then_applies(setup):
    org, _, version, client = setup
    response = upload(client, version, "كفايات.csv", ARABIC_CSV.encode("utf-8-sig"))
    assert response.status_code == 201, response.content
    preview = response.json()
    assert preview["status"] == "previewed"
    assert preview["summary"] == {"create": 3, "update": 0, "unchanged": 0, "errors": 0}
    rows = preview["rows"]
    assert [r["row"] for r in rows] == [2, 3, 5]
    assert rows[0]["values"] == {
        "code": "SAF-01",
        "title": "يحدد مخاطر موقع العمل",
        "description": "وصف أول",
        "level": "2",
        "requirement": "required",
    }
    assert rows[1]["values"]["requirement"] == "optional"
    assert rows[2]["values"]["title"] == "يبلّغ عن الحوادث،  فورًا"
    assert rows[2]["values"]["requirement"] == "required"
    with organization_context(org):
        assert Competency.objects.count() == 0, "nothing is saved before confirmation"

    confirmed = client.post(f"/api/competency-imports/{preview['id']}/confirm/")
    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["status"] == "applied"
    with organization_context(org):
        assert list(version.competencies.values_list("code", "requirement")) == [
            ("SAF-01", "required"),
            ("SAF-02", "optional"),
            ("SAF-03", "required"),
        ]
    assert client.post(f"/api/competency-imports/{preview['id']}/confirm/").status_code == 409


def test_csv_without_bom_and_english_headers(setup):
    _, _, version, client = setup
    content = b"Code,Title,Requirement\nA-1,Identify hazards,optional\n"
    preview = upload(client, version, "c.csv", content).json()
    assert preview["rows"][0]["values"]["requirement"] == "optional"


def test_xlsx_import(setup):
    org, _, version, client = setup
    content = xlsx(
        [["الرمز", "العنوان", "المستوى"], ["X-1", "كفاية من إكسل", 4], [None, None, None], ["X-2", "ثانية", None]]
    )
    preview = upload(client, version, "frame.xlsx", content).json()
    assert [r["values"]["code"] for r in preview["rows"]] == ["X-1", "X-2"]
    assert preview["rows"][0]["values"]["level"] == "4"
    client.post(f"/api/competency-imports/{preview['id']}/confirm/")
    with organization_context(org):
        assert version.competencies.count() == 2


def test_row_errors_are_reported_and_block_confirmation(setup):
    org, _, version, client = setup
    content = (
        "code,title,requirement\n"
        "A-1,first,required\n"
        "A-1,duplicate in file,required\n"
        "A-2,,required\n"
        ",no code,required\n"
        "A-3,bad requirement,sometimes\n"
        f"{'X' * 51},too long code,required\n"
    ).encode()
    preview = upload(client, version, "c.csv", content).json()
    errors = {r["row"]: r["errors"] for r in preview["rows"]}
    assert errors == {
        2: [],
        3: ["duplicate_code_in_file"],
        4: ["missing_title"],
        5: ["missing_code"],
        6: ["invalid_requirement"],
        7: ["code_too_long"],
    }
    assert preview["summary"]["errors"] == 5
    refused = client.post(f"/api/competency-imports/{preview['id']}/confirm/")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "import_has_errors"
    with organization_context(org):
        assert version.competencies.count() == 0


def test_existing_codes_are_updates_and_identical_rows_unchanged(setup):
    org, admin, version, client = setup
    with organization_context(org):
        services.add_competency(version, code="A-1", title="old title")
        services.add_competency(version, code="A-2", title="same", requirement="required")
        key = version.competencies.get(code="A-1").competency_key
    content = b"code,title\nA-1,new title\nA-2,same\nA-3,brand new\n"
    preview = upload(client, version, "c.csv", content).json()
    assert [r["action"] for r in preview["rows"]] == ["update", "unchanged", "create"]
    client.post(f"/api/competency-imports/{preview['id']}/confirm/")
    with organization_context(org):
        updated = version.competencies.get(code="A-1")
        assert updated.title == "new title"
        assert updated.competency_key == key, "updating by code keeps the stable key"
        assert version.competencies.count() == 3


@pytest.mark.parametrize(
    "name,content,code",
    [
        ("c.txt", b"code,title\nA,b\n", "unsupported_file_type"),
        ("c.csv", b"\xff\xfe\x00bad", "file_encoding"),
        ("c.csv", b"title,level\nx,1\n", "missing_columns"),
        ("c.csv", b"", "empty_file"),
        ("c.xlsx", b"not really excel", "unreadable_file"),
    ],
)
def test_file_level_problems_are_rejected_with_a_code(setup, name, content, code):
    _, _, version, client = setup
    response = upload(client, version, name, content)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_files_above_the_size_limit_are_rejected(setup, settings):
    _, _, version, client = setup
    settings.COMPETENCY_IMPORT_MAX_BYTES = 100
    response = upload(client, version, "c.csv", ("code,title\n" + "A,b\n" * 100).encode())
    assert response.json()["error"]["code"] == "file_too_large"


def test_importing_into_a_published_version_is_refused(setup):
    org, admin, version, client = setup
    with organization_context(org):
        services.add_competency(version, code="A", title="a")
        services.publish_version(version, actor=admin)
    response = upload(client, version, "c.csv", b"code,title\nB,b\n")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_locked"


def test_confirming_after_the_version_was_published_is_refused(setup):
    org, admin, version, client = setup
    preview = upload(client, version, "c.csv", b"code,title\nB,b\n").json()
    with organization_context(org):
        services.add_competency(version, code="A", title="a")
        services.publish_version(version, actor=admin)
    assert client.post(f"/api/competency-imports/{preview['id']}/confirm/").json()["error"]["code"] == "version_locked"
