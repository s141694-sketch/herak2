from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.programs.models import ProgramVersion
from apps.tenancy.permissions import HasActiveOrganization, role_required

from . import jobs
from .models import ExportJob


def payload(job: ExportJob | None, *, admin: bool) -> dict:
    if job is None:
        return {"status": "none"}
    body = {
        "status": job.status,
        "attempts": job.attempts,
        "finished_at": job.finished_at,
        "word": {"id": job.word_file_id, "name": job.word_file.name} if job.word_file_id else None,
        "pdf": {"id": job.pdf_file_id, "name": job.pdf_file.name} if job.pdf_file_id else None,
    }
    if admin:
        body["last_error"] = job.last_error  # the technical detail, for whoever can try it again
    return body


def _job(version_pk: int) -> ExportJob | None:
    version = get_object_or_404(ProgramVersion.objects, pk=version_pk)
    return ExportJob.objects.select_related("word_file", "pdf_file", "version").filter(version=version).first()


class VersionExportView(APIView):
    """The export of an approved version (task 7.5): its state, and its Word and PDF files for every member."""

    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        return Response(payload(_job(pk), admin=request.membership.role == Role.ADMIN))


class VersionExportRetryView(APIView):
    """An admin tries a failed export again (spec 7.7: the approval stands; the export is retried)."""

    permission_classes = [role_required(Role.ADMIN)]

    def post(self, request, pk):
        job = _job(pk)
        if job is None:
            from apps.core.errors import Conflict

            raise Conflict("this version has no export", code="export_not_failed")
        jobs.try_again(job, actor=request.user)
        return Response(payload(_job(pk), admin=True))
