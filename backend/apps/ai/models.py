"""The AI gateway's records (phase 4, task 4.4): each organization's policy, every call's usage, and the cache."""

from django.conf import settings
from django.db import models

from apps.tenancy.models import OrganizationScopedModel


class AIPolicy(OrganizationScopedModel):
    """Whether an organization uses AI at all, and how many tokens it may spend a month (spec 5.1.4, 5.4)."""

    class Mode(models.TextChoices):
        AI = "ai", "ai"
        RULES_ONLY = "rules_only", "rules_only"

    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.AI)
    monthly_token_quota = models.PositiveBigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization"], name="ai_one_policy_per_organization")]

    def __str__(self) -> str:
        return f"{self.organization_id}: {self.mode}"

    @property
    def quota(self) -> int:
        return self.monthly_token_quota if self.monthly_token_quota is not None else settings.AI_MONTHLY_TOKEN_QUOTA


class AIUsage(OrganizationScopedModel):
    """One call through the gateway, whatever its outcome; tokens of every attempt count toward the quota."""

    class Status(models.TextChoices):
        OK = "ok", "ok"
        CACHED = "cached", "cached"
        INVALID_OUTPUT = "invalid_output", "invalid_output"
        TIMEOUT = "timeout", "timeout"
        REFUSED = "refused", "refused"
        ERROR = "error", "error"
        QUOTA_EXCEEDED = "quota_exceeded", "quota_exceeded"

    agent = models.CharField(max_length=50)
    prompt_version = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    served_model = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    attempts = models.PositiveSmallIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cache_key = models.CharField(max_length=64)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "created_at"], name="ai_usage_org_time")]

    def __str__(self) -> str:
        return f"{self.agent} {self.status}"


class AICacheEntry(OrganizationScopedModel):
    """A validated output, keyed by content hash, prompt version and model; never shared between organizations."""

    key = models.CharField(max_length=64)
    agent = models.CharField(max_length=50)
    output = models.JSONField()
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "key"], name="ai_cache_key_unique")]

    def __str__(self) -> str:
        return f"{self.agent} {self.key[:12]}"
