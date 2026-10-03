"""Quality reports (spec 4.4): one per program version, rebuilt by each run of the engine.

A report of a draft follows the draft's edits. Once its version leaves draft, the run started at
submission writes the final report and from then on it cannot change, like the version itself.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.db import models

from apps.competencies.models import Competency
from apps.core.errors import Conflict
from apps.programs.models import ProgramVersion
from apps.tenancy.models import OrganizationScopedModel

_engine_writing: ContextVar[bool] = ContextVar("harak2_quality_engine_writing", default=False)


@contextmanager
def engine_write() -> Iterator[None]:
    """Marks writes made by the engine's own run, which may complete the report of a submitted version."""
    token = _engine_writing.set(True)
    try:
        yield
    finally:
        _engine_writing.reset(token)


class ReportLocked(Conflict):
    default_code = "report_locked"
    default_detail = "the quality report of a version that left draft cannot change"


class Severity(models.TextChoices):
    CRITICAL = "critical", "critical"
    WARNING = "warning", "warning"
    INFO = "info", "info"


class Confidence(models.TextChoices):
    HIGH = "high", "high"
    MEDIUM = "medium", "medium"
    LOW = "low", "low"


def _version_is_draft(version_id: int) -> bool:
    return ProgramVersion.all_organizations.filter(pk=version_id, status=ProgramVersion.Status.DRAFT).exists()


class QualityReport(OrganizationScopedModel):
    class Status(models.TextChoices):
        RUNNING = "running", "running"
        COMPLETE = "complete", "complete"
        PARTIAL_RULES_ONLY = "partial_rules_only", "partial_rules_only"
        FAILED = "failed", "failed"

    class Run(models.TextChoices):
        LIGHT = "light", "light"
        FULL = "full", "full"

    version = models.OneToOneField(ProgramVersion, on_delete=models.CASCADE, related_name="quality_report")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RUNNING)
    last_run = models.CharField(max_length=10, choices=Run.choices, default=Run.LIGHT)
    # The latest requested run; a run that finds another id here was superseded and writes nothing.
    run_id = models.UUIDField(default=uuid.uuid4)
    rules_version = models.CharField(max_length=100, blank=True)
    ai_prompts = models.JSONField(default=dict, blank=True)
    ai_models = models.JSONField(default=dict, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    # The AI layer of the latest run: {"status": "none"|"pending"|"done"|"skipped"|"partial", "reasons": [...]}.
    ai_state = models.JSONField(default=dict, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["version"]

    def __str__(self) -> str:
        return f"quality of {self.version_id} ({self.status})"

    def save(self, *args, **kwargs):
        if self.pk and not _engine_writing.get() and not _version_is_draft(self.version_id):
            raise ReportLocked()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not _engine_writing.get() and not _version_is_draft(self.version_id):
            raise ReportLocked()
        return super().delete(*args, **kwargs)


class _ReportRow(OrganizationScopedModel):
    """A row of a report; it changes only while the report's version is a draft, or by the engine's run."""

    report = models.ForeignKey(QualityReport, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True

    def _check_writable(self):
        if _engine_writing.get():
            return
        version_id = QualityReport.all_organizations.filter(pk=self.report_id).values_list("version_id", flat=True)
        if not _version_is_draft(version_id.get()):
            raise ReportLocked()

    def save(self, *args, **kwargs):
        self._check_writable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_writable()
        return super().delete(*args, **kwargs)


class ObjectiveAnalysis(_ReportRow):
    """What the rules (and later the classification agent) found about one objective block."""

    report = models.ForeignKey(QualityReport, on_delete=models.CASCADE, related_name="objectives")
    block_key = models.UUIDField()
    node_key = models.UUIDField()
    content_hash = models.CharField(max_length=64)
    text = models.TextField(blank=True)
    verb = models.CharField(max_length=100, blank=True)
    level_id = models.PositiveSmallIntegerField(default=0)
    level = models.CharField(max_length=50, blank=True)
    # "" when no domain matched (Harak 1's null).
    domain = models.CharField(max_length=20, blank=True)
    confidence = models.CharField(max_length=10, choices=Confidence.choices)
    components = models.JSONField(default=dict)
    score = models.PositiveSmallIntegerField(default=0)
    errors = models.JSONField(default=list)
    dimension = models.JSONField(null=True, blank=True)
    # The classification agent's reading, for the content it was given (ai_content_hash): none, done or failed.
    ai_status = models.CharField(max_length=20, default="none")
    ai_content_hash = models.CharField(max_length=64, blank=True)
    ai_level_id = models.PositiveSmallIntegerField(null=True, blank=True)
    ai_level = models.CharField(max_length=100, blank=True)
    ai_domain = models.CharField(max_length=20, blank=True)
    ai_verb = models.CharField(max_length=100, blank=True)
    ai_confidence = models.CharField(max_length=10, choices=Confidence.choices, blank=True)
    ai_explanation = models.TextField(blank=True)
    ai_model = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["report", "id"]
        constraints = [models.UniqueConstraint(fields=["report", "block_key"], name="quality_objective_unique")]

    def __str__(self) -> str:
        return f"{self.block_key}: {self.level or self.domain}"


class Finding(_ReportRow):
    class Source(models.TextChoices):
        RULE = "rule", "rule"
        AI = "ai", "ai"

    report = models.ForeignKey(QualityReport, on_delete=models.CASCADE, related_name="findings")
    fingerprint = models.CharField(max_length=64)
    kind = models.CharField(max_length=60)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.RULE)
    confidence = models.CharField(max_length=10, choices=Confidence.choices)
    node_key = models.UUIDField(null=True, blank=True)
    block_key = models.UUIDField(null=True, blank=True)
    competency = models.ForeignKey(Competency, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    params = models.JSONField(default=dict, blank=True)
    # Rule findings are explained by the interface from kind and params (translated); AI findings carry text.
    explanation = models.TextField(blank=True)
    dismissed_reason = models.TextField(blank=True)
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["report", "id"]
        constraints = [
            models.UniqueConstraint(fields=["report", "source", "fingerprint"], name="quality_finding_unique")
        ]

    def __str__(self) -> str:
        return f"{self.severity} {self.kind}"

    @property
    def dismissed(self) -> bool:
        return self.dismissed_at is not None


class AICheck(_ReportRow):
    """An agent's judgement that is not about one objective's level: a link's meaning, or a suggested objective
    for an uncovered competency. Kept for the inputs it was made for (basis_hash) and reused while they hold."""

    class Kind(models.TextChoices):
        LINK = "link", "link"
        SUGGESTION = "suggestion", "suggestion"

    report = models.ForeignKey(QualityReport, on_delete=models.CASCADE, related_name="checks")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    subject = models.CharField(max_length=100)
    basis_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20)  # done, failed or rejected (an answer Harak's rules refuse)
    result = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["report", "id"]
        constraints = [models.UniqueConstraint(fields=["report", "kind", "subject"], name="quality_check_unique")]

    def __str__(self) -> str:
        return f"{self.kind} {self.subject}: {self.status}"
