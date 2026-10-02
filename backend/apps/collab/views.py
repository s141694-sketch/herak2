from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.programs import services as program_services
from apps.programs.models import ProgramVersion
from apps.tenancy.permissions import HasActiveOrganization

from . import tokens


class CollabTokenView(APIView):
    """Any active member may open a version live; only collaborators on a draft may write."""

    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        version = get_object_or_404(ProgramVersion.objects.select_related("program"), pk=pk)
        writable = version.is_editable and program_services.can_edit(
            version.program, request.user, request.membership.role
        )
        return Response(tokens.issue(version=version, user=request.user, writable=writable))
