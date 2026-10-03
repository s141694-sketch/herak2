import hashlib

from django.db import models

from apps.programs.models import ProgramVersion
from apps.tenancy.models import OrganizationScopedModel


class DraftDocument(OrganizationScopedModel):
    """The Yjs state of a version's live document (spec 4.3). Django stores it opaquely and never parses it.

    For a draft it is the source of truth for content, and rows are derived from it. Once the version is
    locked, the state is frozen with it, so reviewers' comment anchors and the next draft start from it.
    """

    version = models.OneToOneField(ProgramVersion, on_delete=models.CASCADE, related_name="draft_document")
    state = models.BinaryField()
    state_hash = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    materialized_at = models.DateTimeField(null=True, blank=True)
    issues = models.JSONField(default=list, blank=True)
    # The collaboration service numbers what it sends; an older save arriving late never overwrites a newer one.
    saved_seq = models.BigIntegerField(default=0)
    last_error = models.TextField(blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"live document of {self.version}"

    @staticmethod
    def hash_of(state: bytes) -> str:
        return hashlib.sha256(state).hexdigest()
