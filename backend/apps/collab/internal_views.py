"""Endpoints only the collaboration service may call. The organization comes from the version, not a session."""

import base64
import binascii
import hmac
import json

from django.conf import settings
from django.http import Http404
from rest_framework import exceptions, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.programs.models import ProgramVersion
from apps.tenancy.context import organization_context

from .materialization import rows_from_version
from .models import DraftDocument
from .saving import SaveRejected, editor, record_failure, save_document


class IsCollabService(permissions.BasePermission):
    def has_permission(self, request, view):
        header = request.headers.get("Authorization", "")
        scheme, _, secret = header.partition(" ")
        return scheme == "Service" and hmac.compare_digest(secret.encode(), settings.COLLAB_SERVICE_SECRET.encode())


class SaveTooLarge(exceptions.APIException):
    status_code = 413
    default_code = "document_too_large"
    default_detail = "the live document is larger than the server accepts"


def json_body(request, limit: int) -> dict:
    """The JSON body of a collab save, read with its own size limit.

    A save carries every block twice (rows and Yjs state), so it outgrows the 5 MB limit Django applies to
    request.body (DATA_UPLOAD_MAX_MEMORY_SIZE) long before any block reaches its own limit.
    """
    raw = request._request
    try:
        length = int(raw.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > limit:
        raise SaveTooLarge()
    data = raw.read(limit + 1)
    if len(data) > limit:
        raise SaveTooLarge()
    try:
        body = json.loads(data or b"{}")
    except ValueError as exc:
        raise exceptions.ParseError("the body must be JSON") from exc
    if not isinstance(body, dict):
        raise exceptions.ParseError("the body must be a JSON object")
    return body


class _ServiceView(APIView):
    authentication_classes = []
    permission_classes = [IsCollabService]
    throttle_classes = []

    def version(self, pk) -> ProgramVersion:
        version = ProgramVersion.all_organizations.select_related("program__template_version").filter(pk=pk).first()
        if version is None:
            raise Http404
        return version


class DocumentView(_ServiceView):
    def get(self, request, pk):
        version = self.version(pk)
        with organization_context(version.organization_id):
            draft = DraftDocument.objects.filter(version=version).first()
            if draft is None and version.is_editable:
                # From the moment the live editor holds the document, it is the only writer of the draft's
                # content (D31): REST writes are refused from here on, not only after the first save.
                draft, _ = DraftDocument.objects.get_or_create(version=version, defaults={"state": b""})
            has_state = draft is not None and len(bytes(draft.state)) > 0
            return Response(
                {
                    "version_id": version.pk,
                    "editable": version.is_editable,
                    "level_count": version.program.template_version.levels.count(),
                    "state": base64.b64encode(bytes(draft.state)).decode() if has_state else None,
                    "rows": None if has_state else rows_from_version(version),
                }
            )

    def put(self, request, pk):
        version = self.version(pk)
        body = json_body(request, settings.COLLAB_SAVE_MAX_BYTES)
        with organization_context(version.organization_id):
            try:
                state = base64.b64decode(body.get("state", ""), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise exceptions.ValidationError("state must be base64") from exc
            seq = body.get("seq")
            if seq is not None and (not isinstance(seq, int) or isinstance(seq, bool) or seq < 0):
                raise exceptions.ValidationError("seq must be a non-negative integer")
            try:
                saved = save_document(
                    version, state=state, rows=body.get("rows"), actor=editor(body.get("actor_id")), seq=seq
                )
            except SaveRejected as exc:
                # The editor may unload its copy: what it sent is stored, only the rows lag behind.
                return Response(
                    {"error": {"code": exc.code, "message": str(exc), "details": {"state_saved": True}}}, status=422
                )
            return Response(
                {
                    "ok": True,
                    "stale": saved.stale,
                    "changed_blocks": saved.changed_blocks,
                    "skipped_links": saved.skipped_links,
                }
            )


class DocumentFailureView(_ServiceView):
    def post(self, request, pk):
        version = self.version(pk)
        with organization_context(version.organization_id):
            record_failure(version, str(request.data.get("error", "unknown error")), str(request.data.get("code", "")))
        return Response({"ok": True})
