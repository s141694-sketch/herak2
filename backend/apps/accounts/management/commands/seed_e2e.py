"""Creates the fixed organizations and users the browser tests log in with.

Refuses to run unless HARAK_ALLOW_SEED=1, so it can never touch a real deployment by accident.
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Membership, Organization, Role, User
from apps.tenancy.context import organization_context

ORGANIZATIONS = [("vtc", "مركز التدريب المهني"), ("safety", "أكاديمية السلامة")]
USERS = [
    ("author@example.com", "سارة الحارثية", [("vtc", Role.AUTHOR)]),
    ("multi@example.com", "مازن القنوبي", [("vtc", Role.ADMIN), ("safety", Role.REVIEWER)]),
    ("pending@example.com", "", [("vtc", Role.PENDING)]),
]


class Command(BaseCommand):
    help = "Seed fixed data for browser tests (requires HARAK_ALLOW_SEED=1)."

    def handle(self, *args, **options):
        if os.environ.get("HARAK_ALLOW_SEED") != "1":
            raise CommandError("refusing to seed: set HARAK_ALLOW_SEED=1 in a test environment")
        password = os.environ.get("E2E_PASSWORD", "harak-e2e-password")
        with transaction.atomic():
            orgs = {
                slug: Organization.objects.get_or_create(slug=slug, defaults={"name": name})[0]
                for slug, name in ORGANIZATIONS
            }
            for email, full_name, memberships in USERS:
                user, created = User.objects.get_or_create(email=email, defaults={"full_name": full_name})
                if created:
                    user.set_password(password)
                    user.save()
                for slug, role in memberships:
                    with organization_context(orgs[slug]):
                        Membership.objects.update_or_create(user=user, defaults={"role": role})
        self.stdout.write(self.style.SUCCESS("seeded e2e data"))
