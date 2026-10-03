from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.programs.models import Program, ProgramVersion
from apps.tenancy.models import OrganizationScopedModel


class Comment(OrganizationScopedModel):
    """A note on a block or node (spec 4.5).

    It belongs to the program, not only to the version it was written on, so open comments carry into
    the next version. On text it stores Yjs relative positions; the client resolves them against the
    version's live document, where a deleted position puts the comment under "comments without a place".
    """

    class Category(models.TextChoices):
        MUST_FIX = "must_fix", "must_fix"
        SUGGESTION = "suggestion", "suggestion"

    class Status(models.TextChoices):
        OPEN = "open", "open"
        RESOLVED = "resolved", "resolved"

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="comments")
    version = models.ForeignKey(ProgramVersion, on_delete=models.CASCADE, related_name="comments")
    block_key = models.UUIDField(null=True, blank=True)
    node_key = models.UUIDField(null=True, blank=True)
    anchor = models.JSONField(null=True, blank=True)
    quoted = models.TextField(blank=True)
    body = models.TextField()
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.SUGGESTION)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(block_key__isnull=False) | Q(node_key__isnull=False), name="comments_has_target"
            )
        ]

    def __str__(self) -> str:
        return f"{self.category} on {self.block_key or self.node_key}"


class CommentReply(OrganizationScopedModel):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"reply to {self.comment_id}"
