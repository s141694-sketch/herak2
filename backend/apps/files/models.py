from django.conf import settings
from django.db import models

from apps.tenancy.models import OrganizationScopedModel


class File(OrganizationScopedModel):
    """A file kept in the S3-compatible store (spec 3 storage, 4.6): one uploaded for an import, or one made by an
    export. The row says what it is and where it lies; the bytes never pass through the database."""

    class Kind(models.TextChoices):
        UPLOAD = "upload", "upload"
        EXPORT = "export", "export"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    # The object's key in the store: "<organization>/<kind>/<random>/<name>".
    key = models.CharField(max_length=600, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.name}"
