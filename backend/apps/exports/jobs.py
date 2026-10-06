"""The export on approval (task 7.5; spec 6.4, 7.7; D79). The approval is handled from the audit log (apps.notifications
.automation), which asks for the export once per version. A Celery task makes the Word file (task 7.3) and its PDF
(task 7.4); a failed attempt is tried again at growing intervals, up to MAX_ATTEMPTS, then the job is marked failed
and the organization's admins are told, and an admin may try it again. The approval is never undone. A sweep takes up
an export whose task never ran (the broker was down at the approval) or whose worker was lost. Once both files are
kept, the version moves to "exported" through the single point of transitions."""

from datetime import timedelta

import sentry_sdk
import structlog
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.files import services as files
from apps.files import storage
from apps.files.models import File
from apps.programs import lifecycle
from apps.programs.models import ProgramVersion
from apps.tenancy.context import organization_context

from . import pdf, word
from .models import ExportJob

log = structlog.get_logger("harak2.exports")
S = ProgramVersion.Status
MAX_ATTEMPTS = 5
FIRST_RETRY_SECONDS = 30
WAITING = timedelta(minutes=5)  # a pending job not taken up by then lost its task
RUNNING_TOO_LONG = timedelta(minutes=15)  # a running job not done by then lost its worker
WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def backoff(attempt: int) -> int:
    """Seconds before the next attempt: 30, 60, 120, 240."""
    return FIRST_RETRY_SECONDS * 2 ** (attempt - 1)


@transaction.atomic
def request_export(version: ProgramVersion) -> ExportJob:
    """The export of an approved version, asked for once: the version's row lock keeps two handlings of the
    approval from both creating it."""
    ProgramVersion.objects.select_for_update(no_key=True).get(pk=version.pk)
    job, created = ExportJob.objects.get_or_create(version=version)
    if created:
        transaction.on_commit(lambda: enqueue(job))
    return job


def enqueue(job: ExportJob, *, countdown: int = 0) -> None:
    try:
        generate.apply_async((job.pk,), countdown=countdown, retry=False)
    except Exception as exc:  # the broker being down must not fail what was committed: the sweep takes it up
        log.error("exports.enqueue_failed", job=job.pk, error=str(exc))
        sentry_sdk.capture_exception(exc)


@shared_task(name="exports.generate", ignore_result=True)
def generate(job_id: int) -> None:
    outcome, job = run(job_id)
    if outcome == "retry":
        enqueue(job, countdown=backoff(job.attempts))


def run(job_id: int) -> tuple[str, ExportJob]:
    """One attempt. Returns what follows: "done", "retry", "failed" or "busy" (another attempt is under way)."""
    job = ExportJob.all_organizations.get(pk=job_id)
    with organization_context(job.organization_id):
        with transaction.atomic():
            job = ExportJob.objects.select_for_update().get(pk=job_id)
            if job.status in (ExportJob.Status.DONE, ExportJob.Status.FAILED):
                return job.status, job
            if job.status == ExportJob.Status.RUNNING and job.updated_at > timezone.now() - RUNNING_TOO_LONG:
                return "busy", job
            job.status, job.attempts = ExportJob.Status.RUNNING, job.attempts + 1
            job.save(update_fields=["status", "attempts", "updated_at"])
        version = ProgramVersion.objects.select_related("program__organization", "approved_by").get(pk=job.version_id)
        try:
            made = _make(version)
        except Exception as exc:  # any failure of an attempt: told, tried again, never undoing the approval
            log.warning("exports.attempt_failed", job=job.pk, attempt=job.attempts, error=str(exc))
            return _failed(job, version, exc), job
        return _done(job, version, made), job


def _make(version: ProgramVersion) -> tuple[File, File]:
    organization = version.program.organization
    logo = storage.read(organization.logo_file.key) if organization.logo_file_id else None
    docx = word.build(version, logo=logo)
    converted = pdf.from_word(docx)
    name = f"{version.program.title} - {version.number}"
    word_file = files.store(docx, name=f"{name}.docx", content_type=WORD, kind=File.Kind.EXPORT, actor=None)
    pdf_file = files.store(
        converted, name=f"{name}.pdf", content_type="application/pdf", kind=File.Kind.EXPORT, actor=None
    )
    return word_file, pdf_file


@transaction.atomic
def _done(job: ExportJob, version: ProgramVersion, made: tuple[File, File]) -> str:
    job = ExportJob.objects.select_for_update().get(pk=job.pk)
    job.word_file, job.pdf_file = made
    job.status, job.last_error, job.finished_at = ExportJob.Status.DONE, "", timezone.now()
    job.save()
    record("program_version.exported", target=version, payload={"word": made[0].pk, "pdf": made[1].pk})
    if ProgramVersion.objects.get(pk=version.pk).status == S.APPROVED:
        lifecycle.transition(version, S.EXPORTED, actor=None)
    return "done"


@transaction.atomic
def _failed(job: ExportJob, version: ProgramVersion, error: Exception) -> str:
    job = ExportJob.objects.select_for_update().get(pk=job.pk)
    job.last_error = str(error)[:2000]
    final = job.attempts >= MAX_ATTEMPTS
    job.status = ExportJob.Status.FAILED if final else ExportJob.Status.PENDING
    job.save(update_fields=["last_error", "status", "updated_at"])
    if final:
        # Recorded first; the organization's admins are told from the entry (apps.notifications.automation).
        record(
            "program_version.export_failed",
            target=version,
            payload={"attempts": job.attempts, "error": job.last_error[:500]},
        )
        return "failed"
    return "retry"


@transaction.atomic
def try_again(job: ExportJob, *, actor) -> ExportJob:
    """An admin tries a failed export again, from its first attempt."""
    job = ExportJob.objects.select_for_update().get(pk=job.pk)
    if job.status != ExportJob.Status.FAILED:
        from apps.core.errors import Conflict

        raise Conflict("only a failed export is tried again", code="export_not_failed")
    job.status, job.attempts, job.last_error = ExportJob.Status.PENDING, 0, ""
    job.save(update_fields=["status", "attempts", "last_error", "updated_at"])
    record("program_version.export_retried", actor=actor, target=job.version)
    transaction.on_commit(lambda: enqueue(job))
    return job


@shared_task(name="exports.sweep", ignore_result=True)
def sweep() -> None:
    """Takes up exports whose task never ran or whose worker was lost, and approvals with no export yet."""
    now = timezone.now()
    for version in ProgramVersion.all_organizations.filter(status=S.APPROVED, export_job__isnull=True):
        with organization_context(version.organization_id):
            request_export(version)
    stale = ExportJob.all_organizations.filter(status=ExportJob.Status.PENDING, updated_at__lt=now - WAITING) | (
        ExportJob.all_organizations.filter(status=ExportJob.Status.RUNNING, updated_at__lt=now - RUNNING_TOO_LONG)
    )
    for job in stale:
        if job.status == ExportJob.Status.RUNNING:
            ExportJob.all_organizations.filter(pk=job.pk, status=ExportJob.Status.RUNNING).update(
                status=ExportJob.Status.PENDING, updated_at=now
            )
        enqueue(job)
