"""The daily digest (spec 6.5): one email per member who chose it, with what reached them since the last one."""

import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Organization
from apps.tenancy.context import organization_context

from . import messages
from .models import EmailMode, Notification, NotificationPreference

log = structlog.get_logger("harak2.notifications")


def send_all() -> None:
    for organization in Organization.objects.all():
        with organization_context(organization):
            for preference in NotificationPreference.objects.filter(email=EmailMode.DAILY).select_related("user"):
                try:
                    _send(preference)
                except Exception as exc:  # one member's mail must not stop the others'
                    log.error("notifications.digest_failed", user=preference.user_id, error=str(exc))


@transaction.atomic
def _send(preference: NotificationPreference) -> None:
    waiting = list(
        Notification.objects.select_for_update(skip_locked=True)
        .filter(recipient=preference.user, emailed_at__isnull=True)
        .order_by("created_at", "id")
    )
    if not waiting:
        return
    title, text = messages.digest_email(waiting)
    send_mail(title, text, settings.DEFAULT_FROM_EMAIL, [preference.user.email])
    Notification.objects.filter(pk__in=[n.pk for n in waiting]).update(emailed_at=timezone.now())
