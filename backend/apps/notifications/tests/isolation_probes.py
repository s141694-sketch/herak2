import itertools

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.programs.tests.isolation_probes import _version
from apps.tenancy.isolation import Probe, register

_entries = itertools.count(1_000_000)


def _notification(org):
    """A notification for the user the isolation test signs in with, in ``org``: the same person must not see
    another organization's notifications either."""
    recipient = User.objects.filter(email="isolation@example.com").first() or User.objects.create(email="n@example.com")
    return Notification.objects.create(
        recipient=recipient,
        event="task_assigned",
        version=_version(org),
        audit_entry=next(_entries),
    )


register(
    Probe(
        route="notification-list",
        kind="list",
        make=_notification,
        list_ids=lambda body: [n["id"] for n in body["items"]],
    )
)
register(Probe(route="notification-read", kind="action", make=_notification))
