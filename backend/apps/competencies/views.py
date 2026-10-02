from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.permissions import AdminWritesMembersRead

from . import services
from .models import Competency, CompetencyFramework, CompetencyImport, FrameworkVersion
from .serializers import (
    CompetencyImportSerializer,
    CompetencyImportSummarySerializer,
    CompetencySerializer,
    FrameworkSerializer,
    FrameworkVersionDetailSerializer,
    VersionSummarySerializer,
)


class FrameworkListView(generics.ListCreateAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = FrameworkSerializer

    def get_queryset(self):
        return CompetencyFramework.objects.prefetch_related("versions")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        framework = services.create_framework(actor=request.user, **serializer.validated_data)
        return Response(FrameworkSerializer(framework).data, status=status.HTTP_201_CREATED)


class FrameworkDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = FrameworkSerializer
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return CompetencyFramework.objects.prefetch_related("versions")


class FrameworkVersionsView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def get(self, request, pk):
        framework = get_object_or_404(CompetencyFramework.objects, pk=pk)
        return Response(VersionSummarySerializer(framework.versions.all(), many=True).data)

    def post(self, request, pk):
        framework = get_object_or_404(CompetencyFramework.objects, pk=pk)
        version = services.new_version(framework, actor=request.user)
        return Response(VersionSummarySerializer(version).data, status=status.HTTP_201_CREATED)


class FrameworkVersionDetailView(generics.RetrieveAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = FrameworkVersionDetailSerializer

    def get_queryset(self):
        return FrameworkVersion.objects.select_related("framework", "published_by").prefetch_related("competencies")


class PublishVersionView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def post(self, request, pk):
        version = get_object_or_404(FrameworkVersion.objects, pk=pk)
        version = services.publish_version(version, actor=request.user)
        return Response(VersionSummarySerializer(version).data)


class VersionCompetenciesView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def get(self, request, pk):
        version = get_object_or_404(FrameworkVersion.objects, pk=pk)
        return Response(CompetencySerializer(version.competencies.all(), many=True).data)

    def post(self, request, pk):
        version = get_object_or_404(FrameworkVersion.objects, pk=pk)
        serializer = CompetencySerializer(data=request.data, context={"version": version})
        serializer.is_valid(raise_exception=True)
        competency = services.add_competency(version, **serializer.validated_data)
        return Response(CompetencySerializer(competency).data, status=status.HTTP_201_CREATED)


class CompetencyDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = CompetencySerializer
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return Competency.objects.select_related("version")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if "pk" in self.kwargs:
            context["version"] = self.get_object().version
        return context


class VersionImportsView(APIView):
    permission_classes = [AdminWritesMembersRead]
    parser_classes = [MultiPartParser, JSONParser]

    def get(self, request, pk):
        version = get_object_or_404(FrameworkVersion.objects, pk=pk)
        return Response(CompetencyImportSummarySerializer(version.imports.all(), many=True).data)

    def post(self, request, pk):
        version = get_object_or_404(FrameworkVersion.objects, pk=pk)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError("attach the file in the 'file' field", code="missing_file")
        data = upload.read(settings.COMPETENCY_IMPORT_MAX_BYTES + 1)
        batch = services.preview_import(version, file_name=upload.name, data=data, actor=request.user)
        return Response(CompetencyImportSerializer(batch).data, status=status.HTTP_201_CREATED)


class ImportDetailView(generics.RetrieveAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = CompetencyImportSerializer

    def get_queryset(self):
        return CompetencyImport.objects.all()


class ConfirmImportView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def post(self, request, pk):
        batch = get_object_or_404(CompetencyImport.objects, pk=pk)
        batch = services.confirm_import(batch, actor=request.user)
        return Response(CompetencyImportSerializer(batch).data)
