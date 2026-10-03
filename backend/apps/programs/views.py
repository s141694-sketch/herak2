from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership
from apps.tenancy.permissions import HasActiveOrganization

from . import diff, lifecycle, services
from .models import AlignmentLink, Block, Node, Program, ProgramCollaborator, ProgramVersion
from .serializers import (
    AlignmentLinkSerializer,
    AlignmentLinkWriteSerializer,
    BlockSerializer,
    BlockWriteSerializer,
    CollaboratorSerializer,
    NodeMoveSerializer,
    NodeSerializer,
    NodeWriteSerializer,
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
        return Response(ProgramSerializer(program, context={"request": request}).data, status=status.HTTP_201_CREATED)


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
        return Response(ProgramSerializer(self.get_object(), context={"request": request}).data)


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
        return Response(VersionDetailSerializer(version, context={"request": request}).data["targets"])

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


# --- Tree, nodes and blocks (task 2.5) ---------------------------------------------------------


def _node_in(version, node_id) -> Node | None:
    if node_id is None:
        return None
    node = Node.objects.filter(pk=node_id, version=version).first()
    if node is None:
        raise services.ProgramError("the node must belong to the same version", code="node_parent_invalid")
    return node


class VersionTreeView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        nodes = version.nodes.select_related("parent").order_by("level", "order", "pk")
        blocks = version.blocks.select_related("node").order_by("node_id", "order", "pk")
        return Response(
            {
                "version": VersionSummarySerializer(version).data,
                "nodes": NodeSerializer(nodes, many=True).data,
                "blocks": BlockSerializer(blocks, many=True).data,
            }
        )


class VersionNodesView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        return Response(NodeSerializer(version.nodes.select_related("parent"), many=True).data)

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects.select_related("program"), pk=pk)
        require_edit(request, version.program)
        serializer = NodeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        node = services.add_node(
            version,
            title=data["title"],
            parent=_node_in(version, data.get("parent")),
            order=data.get("order"),
            actor=request.user,
        )
        return Response(NodeSerializer(node).data, status=status.HTTP_201_CREATED)


class NodeDetailView(APIView):
    permission_classes = [HasActiveOrganization]

    def _get(self, pk) -> Node:
        return get_object_or_404(Node.objects.select_related("version__program", "parent"), pk=pk)

    def get(self, request, pk):
        return Response(NodeSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        node = self._get(pk)
        require_edit(request, node.version.program)
        serializer = NodeWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "title" in serializer.validated_data:
            services.update_node(node, title=serializer.validated_data["title"], actor=request.user)
        return Response(NodeSerializer(self._get(pk)).data)

    def delete(self, request, pk):
        node = self._get(pk)
        require_edit(request, node.version.program)
        services.soft_delete_node(node, actor=request.user)
        return Response(NodeSerializer(self._get(pk)).data)


class NodeMoveView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        node = get_object_or_404(Node.objects.select_related("version__program"), pk=pk)
        require_edit(request, node.version.program)
        serializer = NodeMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent = _node_in(node.version, serializer.validated_data["parent"])
        node = services.move_node(node, parent=parent, order=serializer.validated_data["order"], actor=request.user)
        return Response(NodeSerializer(node).data)


class NodeRestoreView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        node = get_object_or_404(Node.objects.select_related("version__program"), pk=pk)
        require_edit(request, node.version.program)
        return Response(NodeSerializer(services.restore_node(node, actor=request.user)).data)


class VersionBlocksView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        return Response(BlockSerializer(version.blocks.select_related("node"), many=True).data)

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects.select_related("program"), pk=pk)
        require_edit(request, version.program)
        serializer = BlockWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "node" not in data or "type" not in data:
            raise exceptions.ValidationError("node and type are required")
        node = Node.objects.filter(pk=data["node"], version=version).first()
        if node is None:
            raise services.ProgramError("the node must belong to the same version", code="block_node_invalid")
        block = services.add_block(
            version,
            node=node,
            type=data["type"],
            content=data.get("content"),
            order=data.get("order"),
            actor=request.user,
        )
        return Response(BlockSerializer(block).data, status=status.HTTP_201_CREATED)


class BlockDetailView(APIView):
    permission_classes = [HasActiveOrganization]

    def _get(self, pk) -> Block:
        return get_object_or_404(Block.objects.select_related("version__program", "node"), pk=pk)

    def get(self, request, pk):
        return Response(BlockSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        block = self._get(pk)
        require_edit(request, block.version.program)
        serializer = BlockWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        node = None
        if "node" in data:
            node = Node.objects.filter(pk=data["node"], version=block.version).first()
            if node is None:
                raise services.ProgramError("the node must belong to the same version", code="block_node_invalid")
        services.update_block(
            block,
            content=data.get("content"),
            type=data.get("type"),
            node=node,
            order=data.get("order"),
            actor=request.user,
        )
        return Response(BlockSerializer(self._get(pk)).data)

    def delete(self, request, pk):
        block = self._get(pk)
        require_edit(request, block.version.program)
        services.soft_delete_block(block, actor=request.user)
        return Response(BlockSerializer(self._get(pk)).data)


class BlockRestoreView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        block = get_object_or_404(Block.objects.select_related("version__program"), pk=pk)
        require_edit(request, block.version.program)
        return Response(BlockSerializer(services.restore_block(block, actor=request.user)).data)


class VersionLinksView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        links = version.alignment_links.select_related("source", "target_block", "target_competency")
        return Response(AlignmentLinkSerializer(links, many=True).data)

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects.select_related("program", "framework_version"), pk=pk)
        require_edit(request, version.program)
        serializer = AlignmentLinkWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def block(block_id):
            if block_id is None:
                return None
            found = Block.objects.filter(pk=block_id, version=version).first()
            if found is None:
                raise services.ProgramError("both ends must belong to this version", code="link_invalid")
            return found

        competency = None
        if data.get("target_competency") is not None:
            competency = version.framework_version.competencies.filter(pk=data["target_competency"]).first()
            if competency is None:
                raise services.ProgramError(
                    "the competency must belong to this version's framework", code="link_invalid"
                )
        created = services.link(
            version,
            kind=data["kind"],
            source=block(data["source"]),
            target=block(data.get("target_block")),
            competency=competency,
            actor=request.user,
        )
        return Response(AlignmentLinkSerializer(created).data, status=status.HTTP_201_CREATED)


class LinkDetailView(APIView):
    permission_classes = [HasActiveOrganization]

    def _get(self, pk) -> AlignmentLink:
        return get_object_or_404(
            AlignmentLink.objects.select_related("version__program", "source", "target_block", "target_competency"),
            pk=pk,
        )

    def get(self, request, pk):
        return Response(AlignmentLinkSerializer(self._get(pk)).data)

    def delete(self, request, pk):
        alignment_link = self._get(pk)
        require_edit(request, alignment_link.version.program)
        services.unlink(alignment_link, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VersionDiffView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk, other):
        before = get_object_or_404(ProgramVersion.objects, pk=pk)
        after = get_object_or_404(ProgramVersion.objects, pk=other)
        for version in {before, after}:
            lifecycle.rows_requested.send(sender=ProgramVersion, version=version)
        return Response(diff.diff_versions(before, after))
