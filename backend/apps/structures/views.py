from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.permissions import AdminWritesMembersRead

from . import services
from .models import StructureTemplate, TemplateVersion
from .serializers import (
    LevelSerializer,
    TemplateSerializer,
    TemplateVersionDetailSerializer,
    TemplateVersionSummarySerializer,
)


class TemplateListView(generics.ListCreateAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = TemplateSerializer

    def get_queryset(self):
        return StructureTemplate.objects.prefetch_related("versions")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = services.create_template(actor=request.user, **serializer.validated_data)
        return Response(TemplateSerializer(template).data, status=status.HTTP_201_CREATED)


class TemplateRenameSerializer(serializers.ModelSerializer):
    versions = TemplateVersionSummarySerializer(many=True, read_only=True)

    class Meta:
        model = StructureTemplate
        fields = ["id", "name", "created_at", "versions"]
        read_only_fields = ["id", "created_at", "versions"]


class TemplateDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = TemplateRenameSerializer
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return StructureTemplate.objects.prefetch_related("versions")


class TemplateVersionsView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def get(self, request, pk):
        template = get_object_or_404(StructureTemplate.objects, pk=pk)
        return Response(TemplateVersionSummarySerializer(template.versions.all(), many=True).data)

    def post(self, request, pk):
        template = get_object_or_404(StructureTemplate.objects, pk=pk)
        version = services.new_version(template, actor=request.user)
        return Response(TemplateVersionSummarySerializer(version).data, status=status.HTTP_201_CREATED)


class TemplateVersionDetailView(generics.RetrieveAPIView):
    permission_classes = [AdminWritesMembersRead]
    serializer_class = TemplateVersionDetailSerializer

    def get_queryset(self):
        return TemplateVersion.objects.select_related("template").prefetch_related("levels")


class TemplateVersionLevelsView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def get(self, request, pk):
        version = get_object_or_404(TemplateVersion.objects, pk=pk)
        return Response(LevelSerializer(version.levels.all(), many=True).data)

    def put(self, request, pk):
        version = get_object_or_404(TemplateVersion.objects, pk=pk)
        serializer = LevelSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        services.set_levels(version, serializer.validated_data, actor=request.user)
        return Response(LevelSerializer(version.levels.all(), many=True).data)


class PublishTemplateVersionView(APIView):
    permission_classes = [AdminWritesMembersRead]

    def post(self, request, pk):
        version = get_object_or_404(TemplateVersion.objects, pk=pk)
        return Response(TemplateVersionSummarySerializer(services.publish_version(version, actor=request.user)).data)
