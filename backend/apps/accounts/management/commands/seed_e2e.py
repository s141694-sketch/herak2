"""Creates the fixed organizations and users the browser tests log in with.

Refuses to run unless HARAK_ALLOW_SEED=1, so it can never touch a real deployment by accident.
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, Organization, Role, TOTPDevice, User
from apps.sso.models import ExternalIdentity, IdentityProviderConfig, VerifiedDomain
from apps.tenancy.context import organization_context
from apps.workflows.models import WorkflowTemplate
from apps.workflows.services import save_template

ORGANIZATIONS = [("vtc", "مركز التدريب المهني"), ("safety", "أكاديمية السلامة"), ("sso", "معهد حرفة")]
USERS = [
    ("author@example.com", "سارة الحارثية", [("vtc", Role.AUTHOR)]),
    ("multi@example.com", "مازن القنوبي", [("vtc", Role.ADMIN), ("safety", Role.REVIEWER)]),
    ("pending@example.com", "", [("vtc", Role.PENDING)]),
    ("reviewer@example.com", "خالد البلوشي", [("vtc", Role.REVIEWER)]),
    ("approver@example.com", "منى الرواحية", [("vtc", Role.APPROVER)]),
    # Single sign-on (phase 6): the institute's admin, and a member of its domain who also had a password.
    ("sso-admin@example.com", "سالم المعمري", [("sso", Role.ADMIN)]),
    ("hamed@vtc.test", "حامد الكندي", [("sso", Role.AUTHOR)]),
    # An account of another organization, whom the training center invites (D90).
    ("guest@example.com", "ضيف من مؤسسة السلامة", [("safety", Role.AUTHOR)]),
]
# The institute's email domain, matching the Keycloak test realm vtc (infra/keycloak). Its DNS TXT verification is
# tested in the backend with a fake resolver; here it is seeded as verified.
SSO_DOMAIN = "vtc.test"
# The training center's default approval workflow: a reviewer, then an approver (spec 6.1).
WORKFLOW = [
    {"name": "المراجعة الفنية", "assignee_role": Role.REVIEWER, "due_work_days": 2},
    {"name": "الاعتماد", "assignee_role": Role.APPROVER, "due_work_days": 1},
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
                        Membership.with_invitations.update_or_create(
                            user=user, defaults={"role": role, "accepted_at": timezone.now()}
                        )
            with organization_context(orgs["vtc"]):
                # Each run invites the guest afresh.
                Membership.with_invitations.filter(user__email="guest@example.com").delete()
            _reset_single_sign_on(orgs["sso"])
            with organization_context(orgs["vtc"]):
                if not WorkflowTemplate.objects.exists():
                    admin = User.objects.get(email="multi@example.com")
                    save_template(None, actor=admin, name="مسار الاعتماد", is_default=True, stages=WORKFLOW)
        self.stdout.write(self.style.SUCCESS("seeded e2e data"))


def _reset_single_sign_on(organization) -> None:
    """The institute starts each run with nothing set up: no provider, its default sign-in rules, its one verified
    domain, no second factor for its admin, and none of the members earlier sign-ins brought (people are kept: the
    audit log refers to them)."""
    keep = {"sso-admin@example.com", "hamed@vtc.test"}
    Organization.objects.filter(pk=organization.pk).update(
        mfa_required_for_managers=False,
        sso_session_hours=Organization._meta.get_field("sso_session_hours").default,
    )
    with organization_context(organization):
        IdentityProviderConfig.objects.all().delete()
        ExternalIdentity.objects.all().delete()
        VerifiedDomain.objects.exclude(domain=SSO_DOMAIN).delete()
        Membership.with_invitations.exclude(user__email__in=keep).delete()
        Membership.objects.filter(user__email="hamed@vtc.test").update(role=Role.AUTHOR)
        admin = User.objects.get(email="sso-admin@example.com")
        TOTPDevice.objects.filter(user=admin).delete()
        VerifiedDomain.objects.get_or_create(
            domain=SSO_DOMAIN, defaults={"token": "seeded", "verified_at": timezone.now(), "created_by": admin}
        )
