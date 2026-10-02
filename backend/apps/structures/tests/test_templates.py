import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.audit.models import AuditLog
from apps.core.locking import VersionLocked
from apps.structures import services
from apps.structures.models import Level
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db

FOUR_LEVELS = [
    {"name_ar": "برنامج", "name_en": "Program"},
    {"name_ar": "وحدة", "name_en": "Module"},
    {"name_ar": "درس", "name_en": "Lesson"},
    {"name_ar": "نشاط", "name_en": "Activity"},
]


@pytest.fixture
def ctx():
    org = Organization.objects.create(name="A", slug="a")
    actor = User.objects.create_user(email="admin@example.com", password="x" * 12)
    with organization_context(org):
        Membership.objects.create(user=actor, role=Role.ADMIN)
        yield org, actor


def test_create_template_with_ordered_bilingual_levels(ctx):
    _, actor = ctx
    template = services.create_template(name="قالب البرامج", actor=actor, levels=FOUR_LEVELS)
    version = template.versions.get()
    assert (version.number, version.status) == (1, "draft")
    assert list(version.levels.values_list("depth", "name_ar", "name_en")) == [
        (0, "برنامج", "Program"),
        (1, "وحدة", "Module"),
        (2, "درس", "Lesson"),
        (3, "نشاط", "Activity"),
    ]
    assert AuditLog.objects.filter(event="structure_template.created").exists()


@pytest.mark.parametrize("count", [0, 6])
def test_a_template_has_one_to_five_levels(ctx, count):
    _, actor = ctx
    levels = [{"name_ar": f"م{i}", "name_en": f"L{i}"} for i in range(count)]
    with pytest.raises(services.TemplateError) as excinfo:
        services.create_template(name="T", actor=actor, levels=levels)
    assert excinfo.value.get_codes() == "template_level_count"


def test_level_names_are_required_in_both_languages(ctx):
    _, actor = ctx
    with pytest.raises(services.TemplateError) as excinfo:
        services.create_template(name="T", actor=actor, levels=[{"name_ar": "وحدة", "name_en": " "}])
    assert excinfo.value.get_codes() == "template_level_name_missing"


def test_set_levels_replaces_them_while_draft(ctx):
    _, actor = ctx
    version = services.create_template(name="T", actor=actor, levels=FOUR_LEVELS).versions.get()
    services.set_levels(version, FOUR_LEVELS[:2], actor=actor)
    assert version.levels.count() == 2


def test_published_versions_are_locked_and_new_versions_are_independent(ctx):
    _, actor = ctx
    template = services.create_template(name="T", actor=actor, levels=FOUR_LEVELS)
    v1 = template.versions.get()
    services.publish_version(v1, actor=actor)
    with pytest.raises(VersionLocked):
        services.set_levels(v1, FOUR_LEVELS[:1], actor=actor)
    level = v1.levels.first()
    level.name_en = "x"
    with pytest.raises(VersionLocked):
        level.save()
    with pytest.raises(VersionLocked):
        Level.objects.filter(version=v1).delete()

    v2 = services.new_version(template, actor=actor)
    assert (v2.number, v2.status) == (2, "draft")
    assert v2.levels.count() == 4
    services.set_levels(v2, FOUR_LEVELS[:3], actor=actor)
    assert v1.levels.count() == 4
    assert template.latest_published() == v1


def test_api_round_trip(ctx):
    org, actor = ctx
    client = APIClient()
    client.post("/api/auth/login/", {"email": "admin@example.com", "password": "x" * 12}, format="json")
    created = client.post("/api/structure-templates/", {"name": "قالب", "levels": FOUR_LEVELS}, format="json")
    assert created.status_code == 201, created.content
    version_id = created.json()["versions"][0]["id"]
    detail = client.get(f"/api/template-versions/{version_id}/").json()
    assert [lv["name_en"] for lv in detail["levels"]] == ["Program", "Module", "Lesson", "Activity"]

    six = [{"name_ar": f"م{i}", "name_en": f"L{i}"} for i in range(6)]
    too_many = client.put(f"/api/template-versions/{version_id}/levels/", six, format="json")
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "template_level_count"

    assert client.put(f"/api/template-versions/{version_id}/levels/", FOUR_LEVELS[:3], format="json").status_code == 200
    assert client.post(f"/api/template-versions/{version_id}/publish/").status_code == 200
    locked = client.put(f"/api/template-versions/{version_id}/levels/", FOUR_LEVELS, format="json")
    assert locked.json()["error"]["code"] == "version_locked"
    new = client.post(f"/api/structure-templates/{created.json()['id']}/versions/")
    assert new.status_code == 201 and new.json()["number"] == 2


def test_only_admins_write_templates(ctx):
    org, actor = ctx
    author = User.objects.create_user(email="author@example.com", password="x" * 12)
    Membership.objects.create(user=author, role=Role.AUTHOR)
    client = APIClient()
    client.post("/api/auth/login/", {"email": "author@example.com", "password": "x" * 12}, format="json")
    assert client.get("/api/structure-templates/").status_code == 200
    assert (
        client.post("/api/structure-templates/", {"name": "x", "levels": FOUR_LEVELS}, format="json").status_code == 403
    )
