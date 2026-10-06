"""The platform operator opens an organization for a client with its first training manager (task 8.6, D87): the
one thing no one inside an organization can do for it."""

from io import StringIO

import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from apps.accounts.models import Membership, Organization, Role, User

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
    membership = Membership.all_organizations.get(organization=organization)
    assert (membership.user.email, membership.role) == ("manager@vtc.test", Role.ADMIN)
    [invitation] = mail.outbox
    assert invitation.to == ["manager@vtc.test"] and "/set-password?uid=" in invitation.body
    assert "vtc" in out.getvalue()


def test_an_existing_account_becomes_the_manager_without_a_new_password():
    User.objects.create_user(email="manager@vtc.test", password="an-existing-password-1")
    call_command("create_organization", "--name", "مركز", "--slug", "vtc", "--admin-email", "manager@vtc.test")
    [message] = mail.outbox
    assert "/set-password" not in message.body


def test_a_slug_is_taken_once():
    Organization.objects.create(name="مركز", slug="vtc")
    with pytest.raises(CommandError, match="vtc"):
        call_command("create_organization", "--name", "آخر", "--slug", "vtc", "--admin-email", "x@vtc.test")
    assert Organization.objects.count() == 1 and not mail.outbox
