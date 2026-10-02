import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.locking import LockableVersion, LockableVersionQuerySet, VersionedRow, VersionedRowQuerySet
from apps.tenancy.models import OrganizationScopedModel, OrganizationScopedQuerySet, scoped_managers


class CompetencyFramework(OrganizationScopedModel):
    """A named framework. Its content lives in versions; published versions never change."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def latest_published(self) -> "FrameworkVersion | None":
        return self.versions.filter(status=FrameworkVersion.Status.PUBLISHED).order_by("-number").first()

    def draft(self) -> "FrameworkVersion | None":
        return self.versions.filter(status=FrameworkVersion.Status.DRAFT).first()


class FrameworkVersionQuerySet(LockableVersionQuerySet, OrganizationScopedQuerySet):
    pass


class FrameworkVersion(LockableVersion, OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        PUBLISHED = "published", "published"

    framework = models.ForeignKey(CompetencyFramework, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    published_at = models.DateTimeField(null=True, blank=True)

    objects, all_organizations = scoped_managers(FrameworkVersionQuerySet)

    class Meta:
        ordering = ["framework", "number"]
        constraints = [
            models.UniqueConstraint(fields=["framework", "number"], name="competencies_version_number_unique"),
            models.UniqueConstraint(
                fields=["framework"], condition=Q(status="draft"), name="competencies_one_draft_per_framework"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.framework} v{self.number} ({self.status})"


class CompetencyQuerySet(VersionedRowQuerySet, OrganizationScopedQuerySet):
    pass


class Competency(VersionedRow, OrganizationScopedModel):
    class Requirement(models.TextChoices):
        REQUIRED = "required", "required"
        OPTIONAL = "optional", "optional"

    version = models.ForeignKey(FrameworkVersion, on_delete=models.CASCADE, related_name="competencies")
    # Stable across versions of the same framework.
    competency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    level = models.CharField(max_length=50, blank=True)
    requirement = models.CharField(max_length=20, choices=Requirement.choices, default=Requirement.REQUIRED)
    order = models.PositiveIntegerField(default=0)

    objects, all_organizations = scoped_managers(CompetencyQuerySet)

    class Meta:
        ordering = ["version", "order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["version", "code"], name="competencies_code_unique_in_version"),
            models.UniqueConstraint(fields=["version", "competency_key"], name="competencies_key_unique_in_version"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class CompetencyImport(OrganizationScopedModel):
    """A previewed file. Rows are applied to the draft version only on confirmation."""

    class Status(models.TextChoices):
        PREVIEWED = "previewed", "previewed"
        APPLIED = "applied", "applied"

    version = models.ForeignKey(FrameworkVersion, on_delete=models.CASCADE, related_name="imports")
    file_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEWED)
    rows = models.JSONField(default=list)
    summary = models.JSONField(default=dict)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.status})"
