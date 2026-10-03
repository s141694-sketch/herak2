from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.programs.models import ProgramVersion
from apps.programs.views import require_edit
from apps.tenancy.permissions import HasActiveOrganization

from . import services
from .models import Suggestion
from .serializers import DismissSerializer, SuggestionRequestSerializer, SuggestionSerializer


def _suggestions():
    return Suggestion.objects.select_related("requested_by", "decided_by")


class VersionSuggestionsView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects, pk=pk)
        return Response(SuggestionSerializer(_suggestions().filter(version=version), many=True).data)

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects.select_related("program"), pk=pk)
        require_edit(request, version.program)
        serializer = SuggestionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        suggestion = services.request(version, data["kind"], actor=request.user, block_key=data.get("block_key"))
        return Response(
            SuggestionSerializer(_suggestions().get(pk=suggestion.pk)).data, status=status.HTTP_202_ACCEPTED
        )


class SuggestionDetailView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        return Response(SuggestionSerializer(get_object_or_404(_suggestions(), pk=pk)).data)


class _Decision(APIView):
    permission_classes = [HasActiveOrganization]

    def decide(self, request, suggestion):
        raise NotImplementedError

    def post(self, request, pk):
        suggestion = get_object_or_404(Suggestion.objects.select_related("version__program"), pk=pk)
        require_edit(request, suggestion.version.program)
        decided = self.decide(request, suggestion)
        return Response(SuggestionSerializer(_suggestions().get(pk=decided.pk)).data)


class AcceptSuggestionView(_Decision):
    def decide(self, request, suggestion):
        return services.accept(suggestion, actor=request.user)


class DismissSuggestionView(_Decision):
    def decide(self, request, suggestion):
        serializer = DismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return services.dismiss(suggestion, actor=request.user, reason=serializer.validated_data["reason"])
