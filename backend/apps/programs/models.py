from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.competencies.models import Competency, FrameworkVersion
from apps.core.locking import LockableVersion, LockableVersionQuerySet, VersionedRow, VersionedRowQuerySet
from apps.structures.models import TemplateVersion
from apps.tenancy.models import OrganizationScopedModel, OrganizationScopedQuerySet, scoped_managers


class Program(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        IN_REVIEW = "in_review", "in_review"
        APPROVED = "approved", "approved"
        ARCHIVED = "archived", "archived"

    title = models.CharField(max_length=300)
    target_role = models.CharField(max_length=200, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # Fixed for the program's life: its tree is shaped by these levels.
    template_version = models.ForeignKey(TemplateVersion, on_delete=models.PROTECT, related_name="programs")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class ProgramCollaborator(OrganizationScopedModel):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="collaborators")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint(fields=["program", "user"], name="programs_collaborator_unique")]

    def __str__(self) -> str:
        return f"{self.user} on {self.program}"


class ProgramVersionQuerySet(LockableVersionQuerySet, OrganizationScopedQuerySet):
    pass


class ProgramVersion(LockableVersion, OrganizationScopedModel):
    """One version of a program. Only a draft can change; status moves only through programs.lifecycle."""

    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        SUBMITTED = "submitted", "submitted"
        IN_STAGE = "in_stage", "in_stage"
        APPROVED = "approved", "approved"
        EXPORTED = "exported", "exported"
        RETURNED = "returned", "returned"
        WITHDRAWN = "withdrawn", "withdrawn"
        CANCELLED = "cancelled", "cancelled"

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    current_stage = models.PositiveSmallIntegerField(null=True, blank=True)
    framework_version = models.ForeignKey(FrameworkVersion, on_delete=models.PROTECT, related_name="program_versions")
    source_version = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects, all_organizations = scoped_managers(ProgramVersionQuerySet)

    class Meta:
        ordering = ["program", "number"]
        constraints = [
            models.UniqueConstraint(fields=["program", "number"], name="programs_version_number_unique"),
            models.UniqueConstraint(
                fields=["program"], condition=Q(status="draft"), name="programs_one_draft_per_program"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.program} v{self.number} ({self.status})"


class ProgramTargetQuerySet(VersionedRowQuerySet, OrganizationScopedQuerySet):
    pass


class ProgramTarget(VersionedRow, OrganizationScopedModel):
    """A competency this version of the program aims at."""

    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, related_name="targets")
    competency = models.ForeignKey(Competency, on_delete=models.PROTECT, related_name="+")

    objects, all_organizations = scoped_managers(ProgramTargetQuerySet)

    class Meta:
        ordering = ["version", "competency__order"]
        constraints = [models.UniqueConstraint(fields=["version", "competency"], name="programs_target_unique")]

    def __str__(self) -> str:
        return f"{self.version} -> {self.competency}"
