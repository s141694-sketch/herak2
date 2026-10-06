from django.db import models

from apps.files.models import File
from apps.programs.models import ProgramVersion
from apps.tenancy.models import OrganizationScopedModel


class ExportJob(OrganizationScopedModel):
    """The export of one approved version (task 7.5, D79): its attempts, its last error, and the two files it made.
    One per version, however often the approval is handled."""

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        RUNNING = "running", "running"
        DONE = "done", "done"
        FAILED = "failed", "failed"

    version = models.OneToOneField(ProgramVersion, on_delete=models.PROTECT, related_name="export_job")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    word_file = models.ForeignKey(File, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    pdf_file = models.ForeignKey(File, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"export of {self.version_id}: {self.status}"
