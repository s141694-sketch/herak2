from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership
from apps.tenancy.permissions import HasActiveOrganization

from . import lifecycle, services
from .models import Program, ProgramCollaborator, ProgramVersion
from .serializers import (
    CollaboratorSerializer,
    ProgramSerializer,
    ProgramUpdateSerializer,
    VersionDetailSerializer,
    VersionSummarySerializer,
)

S = ProgramVersion.Status


def require_edit(request, program: Program) -> None:
    if not services.can_edit(program, request.user, request.membership.role):
        raise exceptions.PermissionDenied("only the program's collaborators can change it")


def require_manage(request, program: Program) -> None:
    if not services.can_manage(program, request.user, request.membership.role):
        raise exceptions.PermissionDenied("only the program owner or an admin can do this")


class ProgramListView(generics.ListCreateAPIView):
    permission_classes = [HasActiveOrganization]
    serializer_class = ProgramSerializer

    def get_queryset(self):
        return Program.objects.select_related("owner").prefetch_related("versions")

    def create(self, request, *args, **kwargs):
        if request.membership.role not in services.EDITING_ROLES:
            raise exceptions.PermissionDenied("only authors and admins create programs")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        program = services.create_program(
            title=data["title"],
            target_role=data.get("target_role", ""),
            owner=request.user,
            template_version=data["template_version"],
            framework_version=data["framework_version"],
            target_ids=data.get("targets", []),
        )
        return Response(ProgramSerializer(program).data, status=status.HTTP_201_CREATED)


class ProgramDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [HasActiveOrganization]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return Program.objects.select_related("owner").prefetch_related("versions")

    def get_serializer_class(self):
        return ProgramUpdateSerializer if self.request.method == "PATCH" else ProgramSerializer

    def perform_update(self, serializer):
        require_manage(self.request, serializer.instance)
        serializer.save()

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(ProgramSerializer(self.get_object()).data)


class CollaboratorsView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        return Response(CollaboratorSerializer(program.collaborators.select_related("user"), many=True).data)

    def post(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        require_manage(request, program)
        serializer = CollaboratorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["user_email"].strip().lower()
        membership = Membership.objects.select_related("user").filter(user__email=email).first()
        if membership is None:
            raise services.ProgramError(
                "no member of this organization has that email", code="collaborator_not_eligible"
            )
        collaborator = services.add_collaborator(program, membership.user, actor=request.user)
        return Response(CollaboratorSerializer(collaborator).data, status=status.HTTP_201_CREATED)


class CollaboratorDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [HasActiveOrganization]
    serializer_class = CollaboratorSerializer

    def get_queryset(self):
        return ProgramCollaborator.objects.select_related("user", "program")

    def destroy(self, request, *args, **kwargs):
        collaborator = self.get_object()
        require_manage(request, collaborator.program)
        services.remove_collaborator(collaborator, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProgramVersionsView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        return Response(VersionSummarySerializer(program.versions.all(), many=True).data)

    def post(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        require_edit(request, program)
        version = services.start_new_version(program, actor=request.user)
        return Response(VersionSummarySerializer(version).data, status=status.HTTP_201_CREATED)


def version_queryset():
    return ProgramVersion.objects.select_related(
        "program__template_version__template", "framework_version__framework", "source_version"
    )


class VersionDetailView(generics.RetrieveAPIView):
    permission_classes = [HasActiveOrganization]
    serializer_class = VersionDetailSerializer

    def get_queryset(self):
        return version_queryset()


class VersionTargetsView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(version_queryset(), pk=pk)
        return Response(VersionDetailSerializer(version).data["targets"])

    def put(self, request, pk):
        version = get_object_or_404(version_queryset(), pk=pk)
        require_edit(request, version.program)
        if not isinstance(request.data, list) or not all(isinstance(i, int) for i in request.data):
            raise exceptions.ValidationError("send a list of competency ids")
        services.set_targets(version, request.data, actor=request.user)
        return Response(VersionDetailSerializer(version).data["targets"])


class _TransitionView(APIView):
    permission_classes = [HasActiveOrganization]
    target_status: str

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        require_edit(request, version.program)
        version = lifecycle.transition(version, self.target_status, actor=request.user)
        return Response(VersionSummarySerializer(version).data)


class SubmitVersionView(_TransitionView):
    target_status = S.SUBMITTED


class WithdrawVersionView(_TransitionView):
    target_status = S.WITHDRAWN
