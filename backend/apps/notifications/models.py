"""Notifications in the platform and by email (spec 6.5, task 5.8).

A Notification is made by the automations (apps.notifications.automation) from an audit log entry, for one
person. Each member chooses how email follows: at once, in a daily digest, or not at all (D59).
"""

from django.conf import settings
from django.db import models

from apps.programs.models import ProgramVersion
from apps.tenancy.models import OrganizationScopedModel


class EmailMode(models.TextChoices):
    IMMEDIATE = "immediate", "immediate"
    DAILY = "daily", "daily"
    OFF = "off", "off"


class NotificationPreference(OrganizationScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    email = models.CharField(max_length=20, choices=EmailMode.choices, default=EmailMode.IMMEDIATE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="notifications_one_preference")]

    def __str__(self) -> str:
        return f"{self.user}: {self.email}"


class Notification(OrganizationScopedModel):
    class Event(models.TextChoices):
        TASK_ASSIGNED = "task_assigned", "task_assigned"
        VERSION_RETURNED = "version_returned", "version_returned"
        VERSION_APPROVED = "version_approved", "version_approved"
        TASK_DUE_SOON = "task_due_soon", "task_due_soon"
        TASK_DUE = "task_due", "task_due"
        TASK_OVERDUE = "task_overdue", "task_overdue"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    event = models.CharField(max_length=30, choices=Event.choices)
    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    # The audit log entry it came from: one notification per entry, person and event, however often it is handled.
    audit_entry = models.BigIntegerField()
    params = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["audit_entry", "recipient", "event"], name="notifications_once")]
        indexes = [models.Index(fields=["organization", "recipient", "read_at"], name="notifications_inbox")]

    def __str__(self) -> str:
        return f"{self.recipient}: {self.event}"
