"""Joining an organization takes the person's acceptance (D90, F7 of the phase 8 review). An admin who adds an
existing account makes an invitation: until its owner accepts it, it grants nothing, it shows the admin the email
alone, and it does not count anywhere another organization looks (the second factor's reset among them). Choosing a
password from the invitation's link proves the email and accepts; so does signing in through the provider of the
organization that invited."""

import io
import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
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
        people["person"] = member("person@b.test", Role.AUTHOR)
    for user in User.objects.all():
        user.set_password(PASSWORD)
        user.save()
    User.objects.filter(email="person@b.test").update(full_name="الاسم في ب")
    yield {"a": a, "b": b, **people}
    cache.clear()


def signed_in(email):
    client = APIClient()
    answer = client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    client.session_data = answer.json()
    return client


def invite(email="person@b.test", role="reviewer"):
    return signed_in("admin@a.test").post(
        "/api/organizations/current/members/", {"email": email, "full_name": "اسم آخر", "role": role}, format="json"
    )


def invitation_id(world):
    return Membership.including_invitations.get(user=world["person"], organization=world["a"]).pk


# --- What an invitation is before it is accepted ---------------------------------------------------------------


def test_an_existing_account_is_invited_and_the_admin_sees_its_email_alone(world):
    TOTPDevice.objects.create(user=world["person"], secret_encrypted="x", confirmed_at="2026-10-01T00:00:00Z")
    answer = invite()
    assert answer.status_code == 201, answer.content
    data = answer.json()
    assert data["status"] == "invited" and data["role"] == "reviewer"
    assert data["user"] == {"id": None, "email": "person@b.test", "full_name": ""}
    assert "mfa_enabled" not in data
    listed = {
        m["user"]["email"]: m for m in signed_in("admin@a.test").get("/api/organizations/current/members/").json()
    }
    assert listed["person@b.test"]["status"] == "invited" and listed["person@b.test"]["user"]["full_name"] == ""
    assert "mfa_enabled" not in listed["person@b.test"]
    assert listed["author@a.test"]["status"] == "member" and listed["author@a.test"]["mfa_enabled"] is False
    # The name the other organization knows stays theirs; the one typed here is not written over it.
    assert User.objects.get(email="person@b.test").full_name == "الاسم في ب"
    [message] = mail.outbox
    assert "مركز أ" in message.body and not LINK.search(message.body)


def test_an_invitation_grants_nothing_until_it_is_accepted(world):
    invite()
    session = signed_in("person@b.test").session_data
    assert [m["organization"]["slug"] for m in session["memberships"]] == ["b"]
    assert session["invitations"] == [
        {
            "id": invitation_id(world),
            "organization": {"id": world["a"].pk, "name": "مركز أ", "slug": "a"},
            "role": "reviewer",
        }
    ]
    client = signed_in("person@b.test")
    refused = client.post("/api/auth/switch-organization/", {"organization_id": world["a"].pk}, format="json")
    assert refused.status_code in (403, 404, 409)
    with organization_context(world["a"]):
        assert not Membership.objects.filter(user=world["person"]).exists()
        assert Membership.with_invitations.filter(user=world["person"]).exists()
    assert not Membership.all_organizations.filter(user=world["person"], organization=world["a"]).exists()


def test_an_invitation_does_not_stop_the_home_organization_resetting_the_second_factor(world):
    TOTPDevice.objects.create(user=world["person"], secret_encrypted="x", confirmed_at="2026-10-01T00:00:00Z")
    invite()
    with organization_context(world["b"]):
        membership = Membership.objects.get(user=world["person"])
    client = signed_in("admin@b.test")
    # admin@b.test has no second factor and b does not require one: the reset is the admin's to make.
    answer = client.post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/")
    assert answer.status_code == 204, answer.content
    assert not TOTPDevice.objects.filter(user=world["person"]).exists()


def test_an_invited_admin_does_not_count_as_the_organizations_admin(world):
    invite(role="admin")
    with organization_context(world["a"]), pytest.raises(members.MemberError) as refused:
        members.set_role(Membership.objects.get(user=world["admin_a"]), role=Role.AUTHOR, actor=world["admin_a"])
    assert refused.value.detail.code == "last_admin"


# --- Accepting, declining, cancelling ---------------------------------------------------------------------------


def test_the_person_accepts_and_works_in_the_organization(world):
    invite()
    client = signed_in("person@b.test")
    answer = client.post(f"/api/auth/invitations/{invitation_id(world)}/accept/")
    assert answer.status_code == 200, answer.content
    assert sorted(m["organization"]["slug"] for m in answer.json()["memberships"]) == ["a", "b"]
    assert answer.json()["invitations"] == []
    entered = client.post("/api/auth/switch-organization/", {"organization_id": world["a"].pk}, format="json")
    assert entered.status_code == 200 and entered.json()["organization"]["role"] == "reviewer"
    listed = {
        m["user"]["email"]: m for m in signed_in("admin@a.test").get("/api/organizations/current/members/").json()
    }
    assert listed["person@b.test"]["status"] == "member"
    assert listed["person@b.test"]["user"]["full_name"] == "الاسم في ب"
    assert AuditLog.all_organizations.filter(event="membership.accepted", organization=world["a"]).exists()


def test_the_person_declines_and_the_invitation_is_gone(world):
    invite()
    answer = signed_in("person@b.test").post(f"/api/auth/invitations/{invitation_id(world)}/decline/")
    assert answer.status_code == 200 and answer.json()["invitations"] == []
    assert not Membership.including_invitations.filter(user=world["person"], organization=world["a"]).exists()
    assert AuditLog.all_organizations.filter(event="membership.declined", organization=world["a"]).exists()


def test_only_the_invited_person_answers_an_invitation(world):
    invite()
    for email in ("author@a.test", "admin@a.test", "admin@b.test"):
        client = signed_in(email)
        assert client.post(f"/api/auth/invitations/{invitation_id(world)}/accept/").status_code == 404
        assert client.post(f"/api/auth/invitations/{invitation_id(world)}/decline/").status_code == 404
    with organization_context(world["a"]):
        own = Membership.objects.get(user=world["author_a"]).pk
    # A membership already accepted is not an invitation: it is not declined this way.
    assert signed_in("author@a.test").post(f"/api/auth/invitations/{own}/decline/").status_code == 404


def test_an_admin_cancels_an_invitation_and_changes_its_role_but_removes_no_member(world):
    invite()
    admin = signed_in("admin@a.test")
    changed = admin.patch(
        f"/api/organizations/current/members/{invitation_id(world)}/", {"role": "approver"}, format="json"
    )
    assert changed.status_code == 200 and changed.json()["role"] == "approver"
    with organization_context(world["a"]):
        accepted = Membership.objects.get(user=world["author_a"]).pk
    refused = admin.delete(f"/api/organizations/current/members/{accepted}/")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "member_not_invited"
    assert (
        signed_in("author@a.test").delete(f"/api/organizations/current/members/{invitation_id(world)}/").status_code
        == 403
    )
    pk = invitation_id(world)
    assert admin.delete(f"/api/organizations/current/members/{pk}/").status_code == 204
    assert not Membership.including_invitations.filter(pk=pk).exists()
    assert AuditLog.all_organizations.filter(event="membership.invitation_cancelled").exists()


def test_an_invitation_is_made_once(world):
    invite()
    again = invite()
    assert again.status_code == 409 and again.json()["error"]["code"] == "member_exists"


# --- Ways an invitation is accepted -----------------------------------------------------------------------------


def test_a_new_person_accepts_by_choosing_a_password_from_the_link(world):
    invite(email="new@a.test", role="author")
    with organization_context(world["a"]):
        assert not Membership.objects.filter(user__email="new@a.test").exists()
    uid, token, org = LINK.search(mail.outbox[0].body).groups()
    answer = APIClient().post(
        "/api/auth/password/set/",
        {"uid": uid, "token": token, "password": PASSWORD, "organization": org},
        format="json",
    )
    assert answer.status_code == 204
    session = signed_in("new@a.test").session_data
    assert session["organization"]["slug"] == "a" and session["invitations"] == []


def test_a_reset_of_an_account_with_a_password_accepts_nothing(world):
    invite()
    APIClient().post("/api/auth/password/forgot/", {"email": "person@b.test"}, format="json")
    uid, token, org = LINK.search(mail.outbox[-1].body).groups()
    APIClient().post(
        "/api/auth/password/set/", {"uid": uid, "token": token, "password": "another-long-password-2"}, format="json"
    )
    assert Membership.including_invitations.get(pk=invitation_id(world)).accepted_at is None


def test_an_account_that_never_had_a_password_accepts_by_choosing_one(world):
    sso_only = User.objects.create_user(email="sso@b.test", password=None)
    with organization_context(world["b"]):
        Membership.objects.create(user=sso_only, role=Role.AUTHOR)
    invite(email="sso@b.test")
    uid, token, org = LINK.search(mail.outbox[0].body).groups()
    APIClient().post(
        "/api/auth/password/set/",
        {"uid": uid, "token": token, "password": PASSWORD, "organization": org},
        format="json",
    )
    assert Membership.including_invitations.get(user=sso_only, organization=world["a"]).accepted_at is not None


def test_signing_in_through_the_inviting_organizations_provider_accepts(world):
    invite()
    with organization_context(world["a"]):
        members.accept_by_signing_in(world["person"])
        assert Membership.objects.get(user=world["person"]).role == Role.REVIEWER
    # A first sign-in with no invitation makes a pending member, as before (D65).
    newcomer = User.objects.create_user(email="newcomer@a.test", password=None)
    with organization_context(world["a"]):
        members.accept_by_signing_in(newcomer)
        assert Membership.objects.get(user=newcomer).role == Role.PENDING


# --- Memberships made before invitations ------------------------------------------------------------------------


def test_create_organization_makes_an_accepted_first_admin(world):
    call_command("create_organization", name="مركز ج", slug="c", admin_email="first@c.test", stdout=io.StringIO())
    membership = Membership.including_invitations.get(user__email="first@c.test")
    # The first admin has no password yet: the invitation's link accepts, as for anyone new.
    assert membership.role == Role.ADMIN
    uid, token, org = LINK.search(mail.outbox[-1].body).groups()
    APIClient().post(
        "/api/auth/password/set/",
        {"uid": uid, "token": token, "password": PASSWORD, "organization": org},
        format="json",
    )
    assert signed_in("first@c.test").session_data["organization"]["slug"] == "c"
