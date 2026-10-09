from django.core import signing
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.tenancy.permissions import HasActiveOrganization

from . import storage
from .models import File


class FileDownloadView(APIView):
    """The API decides who may have a file; the store then serves it through a link that expires (spec 7.4).
    Exports and the logo are for every member of the organization; an uploaded file, for whoever uploaded it."""

    permission_classes = [HasActiveOrganization]

    def get(self, request, pk):
        visible = File.objects.filter(~Q(kind=File.Kind.UPLOAD) | Q(created_by=request.user))
        file = get_object_or_404(visible, pk=pk)
        response = HttpResponseRedirect(storage.signed_link(file.key, name=file.name, content_type=file.content_type))
        response["Cache-Control"] = "no-store"
        return response


class FileContentView(APIView):
    """The file a signed link names, when files are kept on the server itself (D98). The link is the permission, as
    an S3 signed link is: FileDownloadView signed it after checking who asks, and it lasts FILES_LINK_SECONDS."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            path, name, content_type = storage.open_signed(token)
        except (signing.BadSignature, FileNotFoundError, ValueError, KeyError, TypeError) as exc:
            raise Http404("this link is not valid any more") from exc
        response = FileResponse(path.open("rb"), as_attachment=True, filename=name, content_type=content_type)
        response["Cache-Control"] = "no-store"
        return response
