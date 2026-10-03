"""Endpoints only the collaboration service may call. The organization comes from the version, not a session."""

import base64
import binascii
import hmac

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import exceptions, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership, User
from apps.core.errors import Conflict
from apps.core.locking import VersionLocked
from apps.programs.models import ProgramVersion
from apps.tenancy.context import organization_context

from .materialization import MaterializationError, apply_rows, rows_from_version
from .models import DraftDocument


class IsCollabService(permissions.BasePermission):
    def has_permission(self, request, view):
        header = request.headers.get("Authorization", "")
        scheme, _, secret = header.partition(" ")
        return scheme == "Service" and hmac.compare_digest(secret.encode(), settings.COLLAB_SERVICE_SECRET.encode())


class MaterializationFailed(Conflict):
    status_code = 422
    default_code = "materialization_failed"


class _ServiceView(APIView):
    authentication_classes = []
    permission_classes = [IsCollabService]
    throttle_classes = []

    def version(self, pk) -> ProgramVersion:
        version = ProgramVersion.all_organizations.select_related("program__template_version").filter(pk=pk).first()
        if version is None:
            raise Http404
        return version


def _record_failure(version: ProgramVersion, error: str) -> None:
    draft, _ = DraftDocument.objects.get_or_create(version=version, defaults={"state": b""})
    draft.last_error = error[:2000]
    draft.last_error_at = timezone.now()
    draft.save(update_fields=["last_error", "last_error_at", "updated_at"])


class DocumentView(_ServiceView):
    def get(self, request, pk):
        version = self.version(pk)
        with organization_context(version.organization_id):
            draft = DraftDocument.objects.filter(version=version).first()
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
        with organization_context(version.organization_id):
            if not version.is_editable:
                raise VersionLocked()
            try:
                state = base64.b64decode(request.data.get("state", ""), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise exceptions.ValidationError("state must be base64") from exc
            actor = None
            actor_id = request.data.get("actor_id")
            if actor_id and Membership.objects.filter(user_id=actor_id).exists():
                actor = User.objects.get(pk=actor_id)
            try:
                with transaction.atomic():
                    result = apply_rows(version, request.data.get("rows"), actor=actor)
                    draft, _ = DraftDocument.objects.get_or_create(version=version, defaults={"state": b""})
                    draft.state = state
                    draft.state_hash = DraftDocument.hash_of(state)
                    draft.materialized_at = timezone.now()
                    draft.issues = list((request.data.get("rows") or {}).get("issues", []))
                    draft.last_error = ""
                    draft.last_error_at = None
                    draft.save()
            except MaterializationError as exc:
                _record_failure(version, str(exc))
                raise MaterializationFailed(str(exc)) from exc
            return Response({"ok": True, **result})


class DocumentFailureView(_ServiceView):
    def post(self, request, pk):
        version = self.version(pk)
        with organization_context(version.organization_id):
            _record_failure(version, str(request.data.get("error", "unknown error")))
        return Response({"ok": True})
