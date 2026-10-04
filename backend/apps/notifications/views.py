from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.permissions import HasActiveOrganization

from .email import mode_of_user
from .models import EmailMode, Notification, NotificationPreference
from .serializers import NotificationSerializer

LATEST = 50


class NotificationListView(APIView):
    """The caller's notifications in the active organization (latest first), how many are unread, and how email
    follows them. POST marks them all read and/or sets the email choice."""

    permission_classes = [HasActiveOrganization]

    def _body(self, request):
        mine = Notification.objects.filter(recipient=request.user)
        return {
            "items": NotificationSerializer(mine[:LATEST], many=True).data,
            "unread": mine.filter(read_at__isnull=True).count(),
            "email": mode_of_user(request.user),
        }

    def get(self, request):
        return Response(self._body(request))

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        if "email" in data:
            if data["email"] not in EmailMode.values:
                raise exceptions.ValidationError({"email": "immediate, daily or off"})
            NotificationPreference.objects.update_or_create(user=request.user, defaults={"email": data["email"]})
        if data.get("read_all"):
            Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response(self._body(request))


class NotificationReadView(APIView):
    permission_classes = [HasActiveOrganization]

    def post(self, request, pk):
        notification = get_object_or_404(Notification.objects, pk=pk, recipient=request.user)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)
