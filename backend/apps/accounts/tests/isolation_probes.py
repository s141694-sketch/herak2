from apps.accounts.models import Membership, Role, User
from apps.tenancy.isolation import Probe, register


def _member(org) -> Membership:
    user = User.objects.create_user(email=f"probe-{org.slug}-{User.objects.count()}@example.com", password="x" * 12)
    return Membership.objects.create(user=user, role=Role.AUTHOR)


register(Probe(route="organization-current", kind="current"))
register(Probe(route="member-list", kind="list", make=_member))
register(Probe(route="member-detail", kind="detail", make=_member))
register(Probe(route="member-reset-mfa", kind="action", make=_member))
