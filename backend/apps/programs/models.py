import uuid

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


class NodeQuerySet(VersionedRowQuerySet, OrganizationScopedQuerySet):
    pass


class Node(VersionedRow, OrganizationScopedModel):
    """A node of a version's tree. node_key is stable across versions; level is the depth (0 = root)."""

    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, related_name="nodes")
    node_key = models.UUIDField(default=uuid.uuid4, editable=False)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    level = models.PositiveSmallIntegerField()
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=500)
    deleted = models.BooleanField(default=False)

    objects, all_organizations = scoped_managers(NodeQuerySet)

    class Meta:
        ordering = ["version", "level", "order", "id"]
        constraints = [models.UniqueConstraint(fields=["version", "node_key"], name="programs_node_key_unique")]

    def __str__(self) -> str:
        return self.title


class BlockQuerySet(VersionedRowQuerySet, OrganizationScopedQuerySet):
    pass


class Block(VersionedRow, OrganizationScopedModel):
    class Type(models.TextChoices):
        OBJECTIVE = "objective", "objective"
        CONTENT = "content", "content"
        ACTIVITY = "activity", "activity"
        ASSESSMENT = "assessment", "assessment"
        REFERENCE = "reference", "reference"

    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, related_name="blocks")
    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="blocks")
    block_key = models.UUIDField(default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=Type.choices)
    content = models.JSONField()
    content_hash = models.CharField(max_length=64)
    order = models.PositiveIntegerField(default=0)
    deleted = models.BooleanField(default=False)

    objects, all_organizations = scoped_managers(BlockQuerySet)

    class Meta:
        ordering = ["version", "node", "order", "id"]
        constraints = [models.UniqueConstraint(fields=["version", "block_key"], name="programs_block_key_unique")]

    def __str__(self) -> str:
        return f"{self.type} {self.block_key}"


class AlignmentLinkQuerySet(VersionedRowQuerySet, OrganizationScopedQuerySet):
    pass


class AlignmentLink(VersionedRow, OrganizationScopedModel):
    """An explicit alignment set by an author. AI may only suggest these; it never writes them."""

    class Kind(models.TextChoices):
        OBJECTIVE_COMPETENCY = "objective_competency", "objective_competency"
        ASSESSMENT_OBJECTIVE = "assessment_objective", "assessment_objective"
        OBJECTIVE_PARENT = "objective_parent", "objective_parent"

    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, related_name="alignment_links")
    link_key = models.UUIDField(default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    source = models.ForeignKey(Block, on_delete=models.PROTECT, related_name="outgoing_links")
    target_block = models.ForeignKey(
        Block, on_delete=models.PROTECT, null=True, blank=True, related_name="incoming_links"
    )
    target_competency = models.ForeignKey(Competency, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects, all_organizations = scoped_managers(AlignmentLinkQuerySet)

    class Meta:
        ordering = ["version", "kind", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="objective_competency", target_competency__isnull=False, target_block__isnull=True)
                    | (~Q(kind="objective_competency") & Q(target_block__isnull=False, target_competency__isnull=True))
                ),
                name="programs_link_target_matches_kind",
            ),
            models.UniqueConstraint(fields=["version", "link_key"], name="programs_link_key_unique"),
            models.UniqueConstraint(
                fields=["version", "kind", "source", "target_competency"],
                condition=Q(target_competency__isnull=False),
                name="programs_link_competency_unique",
            ),
            models.UniqueConstraint(
                fields=["version", "kind", "source", "target_block"],
                condition=Q(target_block__isnull=False),
                name="programs_link_block_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.source_id}"
