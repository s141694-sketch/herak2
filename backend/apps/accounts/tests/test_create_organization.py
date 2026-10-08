"""The platform operator opens an organization for a client with its first training manager (task 8.6, D87): the
one thing no one inside an organization can do for it."""

from io import StringIO

import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from apps.accounts.models import Membership, Organization, Role, User
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def committed(monkeypatch):
    monkeypatch.setattr("apps.accounts.members.transaction.on_commit", lambda callback, **kwargs: callback())


def test_an_organization_opens_with_its_first_manager_who_is_invited():
    out = StringIO()
    call_command(
        "create_organization",
        "--name",
        "مركز التدريب المهني",
        "--slug",
        "vtc",
        "--admin-email",
        "Manager@VTC.test",
        stdout=out,
    )
    organization = Organization.objects.get(slug="vtc")
    membership = Membership.including_invitations.get(organization=organization)  # accepted from the link (D90)
    assert (membership.user.email, membership.role) == ("manager@vtc.test", Role.ADMIN)
    [invitation] = mail.outbox
    assert invitation.to == ["manager@vtc.test"] and "/set-password?uid=" in invitation.body
    assert "vtc" in out.getvalue()


def test_an_existing_account_is_invited_to_manage_without_a_new_password():
    User.objects.create_user(email="manager@vtc.test", password="an-existing-password-1")
    call_command("create_organization", "--name", "مركز", "--slug", "vtc", "--admin-email", "manager@vtc.test")
    [message] = mail.outbox
    assert "/set-password" not in message.body
    # The account's owner accepts after signing in, as any invitation of an existing account (D90).
    assert Membership.including_invitations.get(user__email="manager@vtc.test").accepted_at is None


def test_a_slug_is_taken_once():
    organization = Organization.objects.create(name="مركز", slug="vtc")
    with organization_context(organization):
        member("manager@vtc.test", Role.ADMIN)
    with pytest.raises(CommandError, match="vtc"):
        call_command("create_organization", "--name", "آخر", "--slug", "vtc", "--admin-email", "x@vtc.test")
    assert Organization.objects.count() == 1 and not mail.outbox


@pytest.mark.parametrize(
    "arguments, named",
    [
        (["--name", "مركز", "--slug", "V T C", "--admin-email", "x@vtc.test"], "slug"),
        (["--name", "   ", "--slug", "vtc", "--admin-email", "x@vtc.test"], "name"),
        (["--name", "مركز", "--slug", "vtc", "--admin-email", "not-an-email"], "email"),
    ],
)
def test_what_is_given_is_checked_before_anything_is_made(arguments, named):
    with pytest.raises(CommandError, match=named):
        call_command("create_organization", *arguments)
    assert not Organization.objects.exists() and not User.objects.exists() and not mail.outbox
