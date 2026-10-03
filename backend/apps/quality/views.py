from django.shortcuts import get_object_or_404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.programs.models import ProgramVersion
from apps.programs.services import can_edit, can_manage
from apps.tenancy.permissions import HasActiveOrganization

from . import services
from .models import Finding, QualityReport
from .serializers import DismissSerializer, FindingSerializer, QualityReportSerializer


def _report_of(version: ProgramVersion) -> QualityReport:
    queryset = QualityReport.objects.prefetch_related("findings__competency", "findings__dismissed_by", "objectives")
    report = queryset.filter(version=version).first()
    if report is None:
        raise exceptions.NotFound("this version has no quality report yet", code="report_not_found")
    return report


def _refuse(exc: services.QualityError):
    if exc.get_codes() == "quality_not_allowed":
        raise exceptions.PermissionDenied(str(exc.detail)) from exc
    raise exc


class VersionQualityView(APIView):
    """The version's latest quality report, with its findings, objective analyses and roll-up."""

    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        return Response(QualityReportSerializer(_report_of(version)).data)


class VersionQualityRunView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects.select_related("program"), pk=pk)
        role = request.membership.role
        if not (can_edit(version.program, request.user, role) or can_manage(version.program, request.user, role)):
            raise exceptions.PermissionDenied("only the program's editors can run the quality check")
        report = services.request_run(version, QualityReport.Run.FULL, actor=request.user)
        return Response({"id": report.pk, "status": report.status, "run_id": str(report.run_id)}, status=202)


class _FindingAction(APIView):
    permission_classes = [HasActiveOrganization]

    def act(self, request, finding):
        raise NotImplementedError

    def post(self, request, pk):
        finding = get_object_or_404(Finding.objects, pk=pk)
        try:
            finding = self.act(request, finding)
        except services.QualityError as exc:
            _refuse(exc)
        return Response(FindingSerializer(finding).data)


class DismissFindingView(_FindingAction):
    def act(self, request, finding):
        serializer = DismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return services.dismiss(
            finding, reason=serializer.validated_data["reason"], actor=request.user, role=request.membership.role
        )


class RestoreFindingView(_FindingAction):
    def act(self, request, finding):
        return services.restore(finding, actor=request.user, role=request.membership.role)
