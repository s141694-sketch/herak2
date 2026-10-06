"""Opens an organization for a client with its first training manager (task 8.6, D87).

Everything else in the space (members, competencies, templates, the approval workflow, sign-in) the training manager
then sets up from the interface. The manager is invited by email as any added member is: a link to choose a password
if they have no account, a note that they were added if they do.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

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
        if Organization.objects.filter(slug=slug).exists():
            raise CommandError(f"an organization with the slug {slug} exists already")
        with transaction.atomic():
            organization = Organization.objects.create(name=name.strip(), slug=slug)
            with organization_context(organization):
                add_member(organization, email=admin_email, role=Role.ADMIN, actor=None)
        self.stdout.write(
            f"organization {organization.slug} (id {organization.pk}); invitation sent to {admin_email.strip().lower()}"
        )
