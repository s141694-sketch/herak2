"""Suggestions the drafting agent makes on an author's request (spec 5.3, task 4.8), and the author's decision.

The server stores what was asked, what the agent answered and what the author decided; it never applies a
suggestion. An accepted suggestion is written into the live document by the author's own editor (D46), and
every decision is kept to measure the agents in use (spec 5.5).
"""

from django.conf import settings
from django.db import models

from apps.programs.models import ProgramVersion
from apps.tenancy.models import OrganizationScopedModel


class Suggestion(OrganizationScopedModel):
    class Kind(models.TextChoices):
        REWRITE = "rewrite", "rewrite"
        OUTLINE = "outline", "outline"

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        READY = "ready", "ready"
        REJECTED = "rejected", "rejected"  # the agent answered, Harak's rules refused the answer
        FAILED = "failed", "failed"  # no answer: rules-only mode, gate closed, quota, timeout...
        ACCEPTED = "accepted", "accepted"
        DISMISSED = "dismissed", "dismissed"

    OPEN = (Status.PENDING, Status.READY)
    SHOWN = (Status.READY, Status.ACCEPTED, Status.DISMISSED)

    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, related_name="suggestions")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    subject = models.CharField(max_length=100, blank=True)  # the block key of a rewrite
    basis_hash = models.CharField(max_length=64)
    request = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reason = models.CharField(max_length=50, blank=True)
    result = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=50, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["version", "kind", "subject"], name="suggestion_subject")]

    def __str__(self) -> str:
        return f"{self.kind} {self.subject}: {self.status}"
