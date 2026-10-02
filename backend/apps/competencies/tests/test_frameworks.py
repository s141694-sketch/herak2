import pytest
from django.db import IntegrityError

from apps.accounts.models import Organization, User
from apps.audit.models import AuditLog
from apps.competencies import services
from apps.competencies.models import Competency, FrameworkVersion
from apps.core.locking import VersionLocked
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx():
    org = Organization.objects.create(name="A", slug="a")
    actor = User.objects.create_user(email="admin@example.com", password="x" * 12)
    with organization_context(org):
        yield org, actor


def add(version, code, title="عنوان", **extra):
    return services.add_competency(version, code=code, title=title, **extra)


def test_creating_a_framework_starts_a_draft_version_one(ctx):
    _, actor = ctx
    framework = services.create_framework(name="إطار السلامة", actor=actor)
    versions = list(framework.versions.all())
    assert [(v.number, v.status) for v in versions] == [(1, "draft")]
    assert AuditLog.objects.filter(event="competency_framework.created").count() == 1


def test_competencies_are_stored_with_a_stable_key(ctx):
    _, actor = ctx
    version = services.create_framework(name="F", actor=actor).versions.get()
    c = add(version, "SAF-01", "يحدد مخاطر موقع العمل", description="وصف", level="3", requirement="required")
    assert c.competency_key is not None
    assert (c.code, c.title, c.level, c.requirement) == ("SAF-01", "يحدد مخاطر موقع العمل", "3", "required")
    with pytest.raises(IntegrityError):
        add(version, "SAF-01")


def test_publishing_locks_the_version(ctx):
    _, actor = ctx
    version = services.create_framework(name="F", actor=actor).versions.get()
    c = add(version, "A-1")
    services.publish_version(version, actor=actor)
    version.refresh_from_db()
    assert version.status == "published" and version.published_by == actor and version.published_at
    assert AuditLog.objects.filter(event="competency_framework.version_published").count() == 1

    c.title = "changed"
    with pytest.raises(VersionLocked):
        c.save()
    with pytest.raises(VersionLocked):
        c.delete()
    with pytest.raises(VersionLocked):
        add(version, "A-2")
    with pytest.raises(VersionLocked):
        Competency.objects.filter(pk=c.pk).update(title="x")
    with pytest.raises(VersionLocked):
        Competency.objects.filter(pk=c.pk).delete()
    version.status = "draft"
    with pytest.raises(VersionLocked):
        version.save()


def test_an_empty_version_cannot_be_published(ctx):
    _, actor = ctx
    version = services.create_framework(name="F", actor=actor).versions.get()
    with pytest.raises(services.FrameworkError):
        services.publish_version(version, actor=actor)


def test_editing_a_published_framework_creates_a_new_draft_with_the_same_keys(ctx):
    _, actor = ctx
    framework = services.create_framework(name="F", actor=actor)
    v1 = framework.versions.get()
    a = add(v1, "A-1", "أ")
    b = add(v1, "B-1", "ب", requirement="optional")
    services.publish_version(v1, actor=actor)

    v2 = services.new_version(framework, actor=actor)
    assert (v2.number, v2.status) == (2, "draft")
    copied = {c.code: c for c in v2.competencies.all()}
    assert copied["A-1"].competency_key == a.competency_key
    assert copied["B-1"].competency_key == b.competency_key
    assert copied["B-1"].requirement == "optional"

    copied["A-1"].title = "أ معدّل"
    copied["A-1"].save()
    a.refresh_from_db()
    assert a.title == "أ"  # the published version is untouched


def test_only_one_draft_at_a_time(ctx):
    _, actor = ctx
    framework = services.create_framework(name="F", actor=actor)
    with pytest.raises(services.FrameworkError):
        services.new_version(framework, actor=actor)


def test_latest_published_version(ctx):
    _, actor = ctx
    framework = services.create_framework(name="F", actor=actor)
    assert framework.latest_published() is None
    v1 = framework.versions.get()
    add(v1, "A")
    services.publish_version(v1, actor=actor)
    assert framework.latest_published() == v1
    v2 = services.new_version(framework, actor=actor)
    assert framework.latest_published() == v1
    services.publish_version(v2, actor=actor)
    assert framework.latest_published() == v2
    assert FrameworkVersion.objects.filter(framework=framework).count() == 2


def test_the_database_rejects_changes_to_rows_of_a_published_version(ctx):
    from django.db import connection, transaction
    from django.db.utils import DatabaseError

    _, actor = ctx
    version = services.create_framework(name="F", actor=actor).versions.get()
    c = add(version, "A-1")
    services.publish_version(version, actor=actor)
    statements = [
        ("UPDATE competencies_competency SET title = 'x' WHERE id = %s", [c.pk]),
        ("DELETE FROM competencies_competency WHERE id = %s", [c.pk]),
        (
            "INSERT INTO competencies_competency (organization_id, version_id, competency_key, code, title, "
            "description, level, requirement, \"order\") VALUES (%s, %s, gen_random_uuid(), 'N', 'n', '', '', "
            "'required', 9)",
            [version.organization_id, version.pk],
        ),
    ]
    for sql, params in statements:
        with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
