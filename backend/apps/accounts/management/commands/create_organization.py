"""Opens an organization for a client with its first training manager (task 8.6, D87).

Everything else in the space (members, competencies, templates, the approval workflow, sign-in) the training manager
then sets up from the interface. The manager is invited by email as any added member is, through the worker: a link to
choose a password if they have none, a note that they were added if they do.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email, validate_slug
from django.db import IntegrityError, transaction

from apps.accounts.members import add_member
from apps.accounts.models import Organization, Role
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
        if Organization.objects.filter(slug=slug).exists():
            raise CommandError(f"an organization with the slug {slug} exists already")
        try:
            with transaction.atomic():
                organization = Organization.objects.create(name=name, slug=slug)
                with organization_context(organization):
                    add_member(organization, email=email, role=Role.ADMIN, actor=None)
        except IntegrityError as exc:  # made at the same moment by another run
            raise CommandError(f"an organization with the slug {slug} exists already") from exc
        # The worker sends the invitation, and tries again if the mail server refuses it.
        self.stdout.write(f"organization {organization.slug} (id {organization.pk}); invitation queued to {email}")
