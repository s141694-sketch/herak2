from django.shortcuts import get_object_or_404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.programs.models import Program
from apps.tenancy.permissions import HasActiveOrganization

from . import services
from .models import Comment
from .serializers import CommentSerializer, CommentWriteSerializer, ReplySerializer


def _comments():
    return Comment.objects.select_related("author", "resolved_by", "version").prefetch_related("replies__author")


class ProgramCommentsView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        return Response(CommentSerializer(_comments().filter(program=program), many=True).data)

    def post(self, request, pk):
        program = get_object_or_404(Program.objects, pk=pk)
        serializer = CommentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        version = program.versions.filter(pk=data["version"]).first()
        if version is None:
            raise exceptions.ValidationError("the version must belong to this program")
        comment = services.create_comment(
            program=program,
            version=version,
            author=request.user,
            body=data["body"],
            category=data["category"],
            block_key=data.get("block_key"),
            node_key=data.get("node_key"),
            anchor=data.get("anchor"),
            quoted=data.get("quoted", ""),
        )
        return Response(CommentSerializer(_comments().get(pk=comment.pk)).data, status=status.HTTP_201_CREATED)


class CommentDetailView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        return Response(CommentSerializer(get_object_or_404(_comments(), pk=pk)).data)


class CommentRepliesView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        comment = get_object_or_404(_comments(), pk=pk)
        return Response(ReplySerializer(comment.replies.all(), many=True).data)

    def post(self, request, pk):
        comment = get_object_or_404(_comments(), pk=pk)
        serializer = ReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply = services.add_reply(comment, author=request.user, body=serializer.validated_data["body"])
        return Response(ReplySerializer(reply).data, status=status.HTTP_201_CREATED)


class _CommentAction(APIView):
    permission_classes = [HasActiveOrganization]
    action: str

    def post(self, request, pk):
        comment = get_object_or_404(_comments().select_related("program"), pk=pk)
        try:
            getattr(services, self.action)(comment, actor=request.user, role=request.membership.role)
        except services.CommentError as exc:
            if exc.get_codes() == "comment_not_allowed":
                raise exceptions.PermissionDenied(str(exc.detail)) from exc
            raise
        return Response(CommentSerializer(_comments().get(pk=pk)).data)


class ResolveCommentView(_CommentAction):
    action = "resolve"


class ReopenCommentView(_CommentAction):
    action = "reopen"
