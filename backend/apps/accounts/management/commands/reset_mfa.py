"""Removes the second factor of a person who lost it and works in more than one organization (D92).

One organization's admin may not remove it, for it serves the person's other organizations too (D70); the operator
does, once the person's identity is checked outside Harak, and the audit log of each of their organizations records
it. The person sets a new one up at their next sign-in where it is required. An emergency account (D66) keeps its
factor: name another emergency account first.
"""

import structlog
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Membership, TOTPDevice, User
from apps.audit.services import record
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context

log = structlog.get_logger("harak2.accounts")


class Command(BaseCommand):
    help = "Remove the second factor of a person who lost it (check who they are first)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="The person's email.")
        parser.add_argument(
            "--reason", required=True, help="How the person's identity was checked; kept in the audit log."
        )

    def handle(self, *args, email, reason, **options):
        email = email.strip().lower()
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"no account has the email {email!r}")
        if IdentityProviderConfig.all_organizations.filter(emergency_user=user).exists():
            raise CommandError("this person is an emergency account: name another emergency account first")
        reason = reason.strip()
        if not reason:
            raise CommandError("say how the person's identity was checked (--reason)")
        with transaction.atomic():
            removed, _ = TOTPDevice.objects.filter(user=user).delete()
            if not removed:
                raise CommandError(f"{email} has no second factor")
            recorded = []
            for membership in Membership.all_organizations.filter(user=user).select_related("organization"):
                with organization_context(membership.organization_id):
                    record(
                        "mfa.reset",
                        target=membership,
                        payload={"user": user.pk, "by": "operator", "reason": reason},
                    )
                recorded.append(membership.organization.name)
        log.warning("accounts.mfa_reset_by_operator", user=user.pk, organizations=len(recorded))
        where = ", ".join(recorded) if recorded else "no organization: the person is a member of none yet"
        self.stdout.write(self.style.SUCCESS(f"the second factor of {email} was removed; recorded in {where}"))
