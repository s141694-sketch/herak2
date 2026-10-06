from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView

from apps.tenancy.permissions import HasActiveOrganization

from . import storage
from .models import File


class FileDownloadView(APIView):
    """The API decides who may have a file; the store then serves it through a link that expires (spec 7.4).
    Exports are for every member of the organization; an uploaded file, for whoever uploaded it."""

    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        visible = File.objects.filter(~Q(kind=File.Kind.UPLOAD) | Q(created_by=request.user))
        file = get_object_or_404(visible, pk=pk)
        response = HttpResponseRedirect(storage.signed_link(file.key, name=file.name, content_type=file.content_type))
        response["Cache-Control"] = "no-store"
        return response
