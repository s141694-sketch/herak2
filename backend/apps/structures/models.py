from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.locking import LockableVersion, LockableVersionQuerySet, VersionedRow, VersionedRowQuerySet
from apps.tenancy.models import OrganizationScopedModel, OrganizationScopedQuerySet, scoped_managers

MAX_LEVELS = 5


class StructureTemplate(OrganizationScopedModel):
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def latest_published(self) -> "TemplateVersion | None":
        return self.versions.filter(status=TemplateVersion.Status.PUBLISHED).order_by("-number").first()

    def draft(self) -> "TemplateVersion | None":
        return self.versions.filter(status=TemplateVersion.Status.DRAFT).first()


class TemplateVersionQuerySet(LockableVersionQuerySet, OrganizationScopedQuerySet):
    pass


class TemplateVersion(LockableVersion, OrganizationScopedModel):
    """Programs can only use published versions, so a version is locked before anything depends on it."""

    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        PUBLISHED = "published", "published"

    template = models.ForeignKey(StructureTemplate, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects, all_organizations = scoped_managers(TemplateVersionQuerySet)

    class Meta:
        ordering = ["template", "number"]
        constraints = [
            models.UniqueConstraint(fields=["template", "number"], name="structures_version_number_unique"),
            models.UniqueConstraint(
                fields=["template"], condition=Q(status="draft"), name="structures_one_draft_per_template"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template} v{self.number} ({self.status})"


class LevelQuerySet(VersionedRowQuerySet, OrganizationScopedQuerySet):
    pass


class Level(VersionedRow, OrganizationScopedModel):
    """One level of a template. depth 0 is the root of a program tree."""

    version = models.ForeignKey(TemplateVersion, on_delete=models.CASCADE, related_name="levels")
    depth = models.PositiveSmallIntegerField()
    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)

    objects, all_organizations = scoped_managers(LevelQuerySet)

    class Meta:
        ordering = ["version", "depth"]
        constraints = [
            models.UniqueConstraint(fields=["version", "depth"], name="structures_level_depth_unique"),
            models.CheckConstraint(condition=Q(depth__lt=MAX_LEVELS), name="structures_level_depth_max"),
        ]

    def __str__(self) -> str:
        return f"{self.depth}: {self.name_ar} / {self.name_en}"
