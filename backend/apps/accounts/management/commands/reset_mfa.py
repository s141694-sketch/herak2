"""Removes the second factor of a person who lost it and works in more than one organization (D92).

One organization's admin may not remove it, for it serves the person's other organizations too (D70); the operator
does, once the person's identity is checked outside Harak, and the audit log of each of their organizations records
it. The person sets a new one up at their next sign-in where it is required. An emergency account (D66) keeps its
factor: name another emergency account first.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Membership, TOTPDevice, User
from apps.audit.services import record
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context


class Command(BaseCommand):
    help = "Remove the second factor of a person who lost it (check who they are first)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="The person's email.")

    def handle(self, *args, email, **options):
        email = email.strip().lower()
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"no account has the email {email!r}")
        if IdentityProviderConfig.all_organizations.filter(emergency_user=user).exists():
            raise CommandError("this person is an emergency account: name another emergency account first")
        with transaction.atomic():
            removed, _ = TOTPDevice.objects.filter(user=user).delete()
            if not removed:
                raise CommandError(f"{email} has no second factor")
            for membership in Membership.all_organizations.filter(user=user):
                with organization_context(membership.organization_id):
                    record("mfa.reset", target=membership, payload={"user": user.pk, "by": "operator"})
        self.stdout.write(self.style.SUCCESS(f"the second factor of {email} was removed"))
