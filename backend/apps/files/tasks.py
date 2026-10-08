"""How long files uploaded for an import are kept (D93): IMPORT_FILE_RETENTION_DAYS from their upload. Their text is
already in the import's request, so the file itself serves no one after the import; keeping it would only keep
people's documents longer than needed. Exports and logos are not touched."""

from datetime import timedelta

import structlog
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.audit.services import record
from apps.tenancy.context import organization_context

from . import storage
from .models import File

log = structlog.get_logger("harak2.files")


@shared_task(name="files.prune_uploads", ignore_result=True)
def prune_uploads() -> None:
    """Removes each expired upload from the store, then its row. One the store could not remove keeps its row, and
    the next day's run tries again."""
    before = timezone.now() - timedelta(days=settings.IMPORT_FILE_RETENTION_DAYS)
    for file in File.all_organizations.filter(kind=File.Kind.UPLOAD, created_at__lt=before):
        try:
            storage.remove(file.key)
        except Exception as exc:  # noqa: BLE001 - any failure of the store leaves the row for the next run
            log.warning("files.prune_failed", file=file.pk, error=str(exc))
            continue
        with organization_context(file.organization_id):
            record("file.expired", target=file, payload={"name": file.name, "uploaded_at": file.created_at.isoformat()})
            File.objects.filter(pk=file.pk).delete()
