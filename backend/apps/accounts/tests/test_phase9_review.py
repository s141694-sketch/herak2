"""From the independent review of phase 9 (D95): what an invitation shows and to whom, which invitation a password
link accepts, an organization left without an admin, and the operator's reset."""

import io
import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import members
from apps.accounts.models import Membership, Organization, Role, TOTPDevice, User
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "a-long-enough-password-1"
LINK = re.compile(r"/set-password\?uid=([\w-]+)&token=([\w-]+)(?:&org=(\d+))?")


@pytest.fixture(autouse=True)
def committed(monkeypatch):
    monkeypatch.setattr("apps.accounts.members.transaction.on_commit", lambda callback, **kwargs: callback())


@pytest.fixture
def world():
    cache.clear()
    a = Organization.objects.create(name="مركز أ", slug="a")
    b = Organization.objects.create(name="مركز ب", slug="b")
    with organization_context(a):
        people = {"admin_a": member("admin@a.test", Role.ADMIN), "author_a": member("author@a.test", Role.AUTHOR)}
    with organization_context(b):
        people["admin_b"] = member("admin@b.test", Role.ADMIN)
    for user in User.objects.all():
        user.set_password(PASSWORD)
        user.save()
    yield {"a": a, "b": b, **people}
    cache.clear()


def signed_in(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    return client


def set_password(match, password=PASSWORD, with_org=True):
    uid, token, org = match.groups()
    body = {"uid": uid, "token": token, "password": password}
    if with_org and org:
        body["organization"] = int(org)
    return APIClient().post("/api/auth/password/set/", body, format="json")


def test_only_an_admin_sees_invitations_and_never_the_accounts_id(world):
    answer = signed_in("admin@a.test").post(
        "/api/organizations/current/members/", {"email": "admin@b.test", "role": "author"}, format="json"
    )
    assert answer.json()["user"]["id"] is None
    listed = {
        m["user"]["email"]: m for m in signed_in("admin@a.test").get("/api/organizations/current/members/").json()
    }
    assert listed["admin@b.test"]["user"]["id"] is None and listed["author@a.test"]["user"]["id"] is not None
    seen = [m["user"]["email"] for m in signed_in("author@a.test").get("/api/organizations/current/members/").json()]
    assert "admin@b.test" not in seen and "author@a.test" in seen


def test_a_password_link_accepts_only_the_invitation_it_was_sent_for(world):
    with organization_context(world["a"]):
        members.add_member(world["a"], email="new@x.test", role=Role.AUTHOR, actor=world["admin_a"])
    with organization_context(world["b"]):
        members.add_member(world["b"], email="new@x.test", role=Role.REVIEWER, actor=world["admin_b"])
    from_a = LINK.search(mail.outbox[0].body)
    assert from_a.group(3) == str(world["a"].pk)
    assert set_password(from_a).status_code == 204
    accepted = dict(
        Membership.including_invitations.filter(user__email="new@x.test").values_list("organization", "accepted_at")
    )
    assert accepted[world["a"].pk] is not None and accepted[world["b"].pk] is None


def test_a_link_without_an_organization_accepts_nothing(world):
    with organization_context(world["a"]):
        members.add_member(world["a"], email="new@x.test", role=Role.AUTHOR, actor=world["admin_a"])
    assert set_password(LINK.search(mail.outbox[0].body), with_org=False).status_code == 204
    assert Membership.including_invitations.get(user__email="new@x.test").accepted_at is None


def test_create_organization_invites_again_an_organization_left_without_an_admin(world):
    call_command("create_organization", name="مركز ج", slug="c", admin_email="admin@a.test", stdout=io.StringIO())
    invitation = Membership.including_invitations.get(organization__slug="c")
    signed_in("admin@a.test").post(f"/api/auth/invitations/{invitation.pk}/decline/")
    assert not Membership.including_invitations.filter(organization__slug="c").exists()
    call_command("create_organization", name="مركز ج", slug="c", admin_email="admin@b.test", stdout=io.StringIO())
    assert Membership.including_invitations.get(organization__slug="c").user.email == "admin@b.test"
    # An organization with an admin who accepted is not opened again.
    with pytest.raises(CommandError, match="exists"):
        call_command("create_organization", name="مركز أ", slug="a", admin_email="x@a.test", stdout=io.StringIO())


def test_reset_mfa_needs_a_reason_and_says_where_it_was_recorded(world):
    person = User.objects.create_user(email="lost@x.test", password=PASSWORD)
    with organization_context(world["a"]):
        Membership.objects.create(user=person, role=Role.AUTHOR)
    TOTPDevice.objects.create(user=person, secret_encrypted="x", confirmed_at=timezone.now())
    with pytest.raises(CommandError):
        call_command("reset_mfa", "--email", "lost@x.test", stdout=io.StringIO())
    out = io.StringIO()
    call_command("reset_mfa", "--email", "lost@x.test", "--reason", "called their manager", stdout=out)
    [entry] = AuditLog.all_organizations.filter(event="mfa.reset")
    assert entry.payload["reason"] == "called their manager" and "مركز أ" in out.getvalue()


def test_reset_mfa_of_one_with_invitations_only_says_nothing_was_recorded(world):
    person = User.objects.create_user(email="invited@x.test", password=PASSWORD)
    with organization_context(world["a"]):
        Membership.with_invitations.create(user=person, role=Role.AUTHOR, accepted_at=None)
    TOTPDevice.objects.create(user=person, secret_encrypted="x", confirmed_at=timezone.now())
    out = io.StringIO()
    call_command("reset_mfa", "--email", "invited@x.test", "--reason", "checked", stdout=out)
    assert not TOTPDevice.objects.filter(user=person).exists()
    assert "no organization" in out.getvalue()
