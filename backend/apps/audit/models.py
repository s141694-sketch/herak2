"""Append-only audit log (task 1.8).

Entries are written only through apps.audit.services.record. The model
refuses every other save, any change to an existing row and any delete, and
a PostgreSQL trigger (migration 0002) rejects UPDATE and DELETE even from raw
SQL. Actors and organizations are protected from deletion while they have
audit history, because a cascade would have to rewrite the log.
"""

from contextvars import ContextVar

from django.conf import settings
from django.db import models

from apps.tenancy.models import OrganizationScopedManager, OrganizationScopedModel, OrganizationScopedQuerySet

_write_allowed: ContextVar[bool] = ContextVar("audit_write_allowed", default=False)


class AuditLogImmutable(RuntimeError):
    """Raised on any attempt to write the audit log outside record(), or to change or remove an entry."""


class AuditLogQuerySet(OrganizationScopedQuerySet):
    def update(self, **kwargs):
        raise AuditLogImmutable("audit log entries cannot be updated")

    def delete(self):
        raise AuditLogImmutable("audit log entries cannot be deleted")

    def bulk_create(self, objs, *args, **kwargs):
        raise AuditLogImmutable("write audit entries through apps.audit.services.record")

    def bulk_update(self, objs, *args, **kwargs):
        raise AuditLogImmutable("audit log entries cannot be updated")


class AuditLogManager(OrganizationScopedManager.from_queryset(AuditLogQuerySet)):
    pass


class AuditLog(OrganizationScopedModel):
    event = models.CharField(max_length=100)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    # Snapshot, so the entry stays readable whatever happens to the account later.
    actor_email = models.EmailField(blank=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditLogManager()
    all_organizations = models.Manager.from_queryset(AuditLogQuerySet)()  # noqa: DJ012

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["organization", "target_type", "target_id"]),
            models.Index(fields=["organization", "event"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None or not self._state.adding:
            raise AuditLogImmutable("audit log entries cannot be changed")
        if not _write_allowed.get():
            raise AuditLogImmutable("write audit entries through apps.audit.services.record")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutable("audit log entries cannot be deleted")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.event}"
