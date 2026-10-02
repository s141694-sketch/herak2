import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.accounts.models import Organization, User
from apps.audit.models import AuditLog, AuditLogImmutable
from apps.audit.services import record
from apps.tenancy.context import OrganizationContextRequired, organization_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return Organization.objects.create(name="A", slug="a")


@pytest.fixture
def actor():
    return User.objects.create_user(email="actor@example.com", password="x" * 12, full_name="مازن")


def test_record_writes_an_entry_in_the_active_organization(org, actor):
    with organization_context(org):
        entry = record("program.created", actor=actor, target=org, payload={"title": "برنامج السلامة"})
        assert entry.pk is not None
        assert entry.organization_id == org.pk
        assert entry.event == "program.created"
        assert entry.actor_id == actor.pk
        assert entry.actor_email == "actor@example.com"
        assert entry.target_type == "accounts.organization"
        assert entry.target_id == str(org.pk)
        assert entry.payload == {"title": "برنامج السلامة"}
        assert entry.created_at is not None
        assert list(AuditLog.objects.values_list("event", flat=True)) == ["program.created"]


def test_record_requires_an_organization_context(actor):
    with pytest.raises(OrganizationContextRequired):
        record("program.created", actor=actor)


def test_system_events_have_no_actor(org):
    with organization_context(org):
        entry = record("reminder.sent")
        assert entry.actor_id is None and entry.actor_email == ""


def test_saving_outside_the_single_write_point_is_rejected(org):
    with organization_context(org):
        with pytest.raises(AuditLogImmutable):
            AuditLog(event="forged").save()
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.create(event="forged")
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.bulk_create([AuditLog(event="forged")])
        assert AuditLog.objects.count() == 0


def test_existing_entries_cannot_be_modified_or_deleted_through_the_orm(org):
    with organization_context(org):
        entry = record("program.created")
        entry.event = "tampered"
        with pytest.raises(AuditLogImmutable):
            entry.save()
        with pytest.raises(AuditLogImmutable):
            entry.delete()
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.filter(pk=entry.pk).update(event="tampered")
        with pytest.raises(AuditLogImmutable):
            AuditLog.objects.filter(pk=entry.pk).delete()
        entry.refresh_from_db()
        assert entry.event == "program.created"


def test_the_database_itself_rejects_update_and_delete(org):
    with organization_context(org):
        entry = record("program.created")
    table = AuditLog._meta.db_table
    for sql in (f"UPDATE {table} SET event = 'tampered' WHERE id = %s", f"DELETE FROM {table} WHERE id = %s"):
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [entry.pk])
    with organization_context(org):
        assert AuditLog.objects.get(pk=entry.pk).event == "program.created"


def test_entries_of_other_organizations_are_invisible(org):
    other = Organization.objects.create(name="B", slug="b")
    with organization_context(org):
        record("a.event")
    with organization_context(other):
        record("b.event")
        assert list(AuditLog.objects.values_list("event", flat=True)) == ["b.event"]


def test_a_user_with_audit_history_cannot_be_deleted(org, actor):
    with organization_context(org):
        record("program.created", actor=actor)
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        actor.delete()
