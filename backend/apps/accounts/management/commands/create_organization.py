"""Opens an organization for a client with its first training manager (task 8.6, D87).

Everything else in the space (members, competencies, templates, the approval workflow, sign-in) the training manager
then sets up from the interface. The manager is invited by email as any added member is, through the worker: a link to
choose a password if they have none, an invitation to accept after signing in if they do (D90).

An organization whose first manager declined, or never accepted, is left with no admin; run the command again with
its slug and another email (or the same) to invite one. An organization with an admin who accepted is not reopened.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email, validate_slug
from django.db import IntegrityError, transaction

from apps.accounts.members import MemberError, add_member
from apps.accounts.models import Membership, Organization, Role
from apps.tenancy.context import organization_context


class Command(BaseCommand):
    help = "Create an organization and invite its first training manager."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="The organization's name as its people know it.")
        parser.add_argument("--slug", required=True, help="A short unique identifier, such as vtc.")
        parser.add_argument("--admin-email", required=True, help="The first training manager's email.")

    def handle(self, *args, name, slug, admin_email, **options):
        name, email = name.strip(), admin_email.strip().lower()
        # Checked before anything is made (phase 8 review).
        try:
            validate_slug(slug)
        except ValidationError as exc:
            raise CommandError(f"the slug {slug!r} is not valid: letters, digits, - and _ only") from exc
        if not name:
            raise CommandError("the organization's name is empty")
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError(f"the admin's email {admin_email!r} is not valid") from exc
        existing = Organization.objects.filter(slug=slug).first()
        if existing is not None:
            self._invite_again(existing, email)
            return
        try:
            with transaction.atomic():
                organization = Organization.objects.create(name=name, slug=slug)
                with organization_context(organization):
                    add_member(organization, email=email, role=Role.ADMIN, actor=None)
        except IntegrityError as exc:  # made at the same moment by another run
            raise CommandError(f"an organization with the slug {slug} exists already") from exc
        # The worker sends the invitation, and tries again if the mail server refuses it.
        self.stdout.write(f"organization {organization.slug} (id {organization.pk}); invitation queued to {email}")

    def _invite_again(self, organization: Organization, email: str) -> None:
        """An organization left with no admin (phase 9 review): its first manager is invited again."""
        with transaction.atomic(), organization_context(organization):
            Organization.objects.select_for_update().get(pk=organization.pk)
            if Membership.objects.filter(role=Role.ADMIN).exists():
                raise CommandError(f"an organization with the slug {organization.slug} exists already")
            # An unanswered invitation of the same organization gives way to this one.
            Membership.with_invitations.filter(role=Role.ADMIN, accepted_at__isnull=True).delete()
            try:
                add_member(organization, email=email, role=Role.ADMIN, actor=None)
            except MemberError as exc:
                raise CommandError(f"{email} is a member already: an admin makes them a manager") from exc
        self.stdout.write(f"organization {organization.slug} had no admin; invitation queued to {email}")
