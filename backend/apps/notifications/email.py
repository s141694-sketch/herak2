"""Sending notifications by email (D59): SMTP from the environment, any provider that speaks it."""

import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.tenancy.context import organization_context

from . import messages
from .models import EmailMode, Notification, NotificationPreference

log = structlog.get_logger("harak2.notifications")


def mode_of_user(user) -> str:
    """How email follows this member's notifications in the active organization; at once unless they chose."""
    preference = NotificationPreference.objects.filter(user=user).first()
    return preference.email if preference else EmailMode.IMMEDIATE


def mode_of(notification: Notification) -> str:
    return mode_of_user(notification.recipient)


def send_now(notifications: list[Notification]) -> None:
    """Emails the notifications whose recipient wants them at once; the others wait for the digest or stay in
    the platform. ``emailed_at`` marks a notification email is done with. A failed email is logged and left
    unmarked, so handling its audit entry again sends it."""
    for notification in notifications:
        with organization_context(notification.organization_id):
            mode = mode_of(notification)
            if mode == EmailMode.OFF:
                # Kept in the platform only: marked as handled, so a later switch to the digest does not send it.
                Notification.objects.filter(pk=notification.pk).update(emailed_at=timezone.now())
                continue
            if mode != EmailMode.IMMEDIATE:
                continue
            try:
                send_mail(
                    messages.subject(notification),
                    messages.body(notification),
                    settings.DEFAULT_FROM_EMAIL,
                    [notification.recipient.email],
                )
            except Exception as exc:
                log.error("notifications.email_failed", notification=notification.pk, error=str(exc))
                continue
            Notification.objects.filter(pk=notification.pk).update(emailed_at=timezone.now())
