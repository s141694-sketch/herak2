"""Members (spec 2.1: the training manager runs the space and its users; D87). An admin adds people by email with a
role, and changes roles. A new person sets their password from the invitation's link; anyone who forgot theirs asks
for a new link. A person who signs in through the organization's provider is told so instead."""

import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import members
from apps.accounts.models import Membership, Organization, Role, User
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "a-long-enough-password-1"
LINK = re.compile(r"/set-password\?uid=([\w-]+)&token=([\w-]+)")


@pytest.fixture(autouse=True)
def committed(monkeypatch):
    """The invitation leaves once the member is committed; tests run inside a transaction that never commits."""
    monkeypatch.setattr("apps.accounts.members.transaction.on_commit", lambda callback, **kwargs: callback())


@pytest.fixture
def world():
    cache.clear()
    org = Organization.objects.create(name="مركز أ", slug="a")
    other = Organization.objects.create(name="مركز ب", slug="b")
    with organization_context(org):
        people = {
            "admin": member("admin@a.test", Role.ADMIN),
            "author": member("author@a.test", Role.AUTHOR),
            "reviewer": member("reviewer@a.test", Role.REVIEWER),
        }
    with organization_context(other):
        people["elsewhere"] = member("elsewhere@b.test", Role.AUTHOR)
    for user in User.objects.all():
        user.set_password(PASSWORD)
        user.save()
    yield {"org": org, "other": other, **people}
    cache.clear()


def signed_in(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    return client


def add(client, email, role="author", full_name=""):
    return client.post(
        "/api/organizations/current/members/", {"email": email, "full_name": full_name, "role": role}, format="json"
    )


def link_in(message) -> tuple[str, str]:
    match = LINK.search(message.body)
    assert match, message.body
    return match.group(1), match.group(2)


def set_password(uid, token, password=PASSWORD):
    return APIClient().post(
        "/api/auth/password/set/", {"uid": uid, "token": token, "password": password}, format="json"
    )


def test_an_admin_adds_a_new_person_who_sets_a_password_from_the_invitation(world):
    added = add(signed_in("admin@a.test"), " New@A.test ", "author", "سالم")
    assert added.status_code == 201, added.content
    assert (added.json()["user"]["email"], added.json()["role"]) == ("new@a.test", "author")
    person = User.objects.get(email="new@a.test")
    assert not person.has_usable_password()
    [invitation] = mail.outbox
    assert invitation.to == ["new@a.test"] and "مركز أ" in invitation.body
    uid, token = link_in(invitation)
    assert set_password(uid, token).status_code == 204
    signed = APIClient().post("/api/auth/login/", {"email": "new@a.test", "password": PASSWORD}, format="json")
    assert signed.status_code == 200 and signed.json()["organization"]["slug"] == "a"
    assert set_password(uid, token, "another-long-password-2").json()["error"]["code"] == "password_link_invalid"
    assert AuditLog.all_organizations.filter(event="membership.added").exists()


def test_a_weak_password_is_refused_by_the_same_rules_as_ever(world):
    add(signed_in("admin@a.test"), "new@a.test")
    uid, token = link_in(mail.outbox[0])
    refused = set_password(uid, token, "12345678")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "password_invalid"


def test_someone_with_an_account_elsewhere_is_added_and_told_without_a_password_link(world):
    added = add(signed_in("admin@a.test"), "elsewhere@b.test", "reviewer")
    assert added.status_code == 201
    [message] = mail.outbox
    assert not LINK.search(message.body)
    assert (
        APIClient()
        .post("/api/auth/login/", {"email": "elsewhere@b.test", "password": PASSWORD}, format="json")
        .status_code
        == 200
    )


def test_in_an_organization_that_signs_in_through_its_provider_the_invitation_says_so(world):
    with organization_context(world["org"]):
        IdentityProviderConfig.objects.create(
            issuer="https://idp.a.test",
            client_id="harak",
            client_secret_encrypted="x",
            enabled=True,
            enforced=True,
            emergency_user=world["admin"],
            config_changed_at=timezone.now(),
        )
        # A password session does not enter an organization that enforces its provider (D66): the service directly.
        members.add_member(world["org"], email="new@a.test", role="author", actor=world["admin"])
    [message] = mail.outbox
    assert not LINK.search(message.body) and "مزوّد" in message.body


def test_a_person_is_a_member_once(world):
    refused = add(signed_in("admin@a.test"), "author@a.test")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "member_exists"


def test_only_an_admin_adds_members_and_changes_roles(world):
    author = signed_in("author@a.test")
    assert add(author, "new@a.test").status_code == 403
    reviewer = Membership.all_organizations.get(user=world["reviewer"])
    assert (
        author.patch(f"/api/organizations/current/members/{reviewer.pk}/", {"role": "admin"}, format="json").status_code
        == 403
    )


def test_an_admin_changes_a_role_and_it_is_audited(world):
    reviewer = Membership.all_organizations.get(user=world["reviewer"])
    changed = signed_in("admin@a.test").patch(
        f"/api/organizations/current/members/{reviewer.pk}/", {"role": "approver"}, format="json"
    )
    assert changed.status_code == 200 and changed.json()["role"] == "approver"
    entry = AuditLog.all_organizations.get(event="membership.role_changed")
    assert entry.payload == {"from": "reviewer", "to": "approver", "user": world["reviewer"].pk}


@pytest.mark.parametrize("role", ["owner", "", "superuser"])
def test_a_role_is_one_of_the_platforms(world, role):
    reviewer = Membership.all_organizations.get(user=world["reviewer"])
    response = signed_in("admin@a.test").patch(
        f"/api/organizations/current/members/{reviewer.pk}/", {"role": role}, format="json"
    )
    assert response.status_code == 400


def test_the_last_admin_keeps_the_role(world):
    admin = Membership.all_organizations.get(user=world["admin"])
    refused = signed_in("admin@a.test").patch(
        f"/api/organizations/current/members/{admin.pk}/", {"role": "author"}, format="json"
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "last_admin"


def test_the_emergency_account_stays_an_admin(world):
    with organization_context(world["org"]):
        second = member("second@a.test", Role.ADMIN)
        IdentityProviderConfig.objects.create(
            issuer="https://idp.a.test",
            client_id="harak",
            client_secret_encrypted="x",
            emergency_user=second,
            config_changed_at=timezone.now(),
        )
    membership = Membership.all_organizations.get(user=second)
    refused = signed_in("admin@a.test").patch(
        f"/api/organizations/current/members/{membership.pk}/", {"role": "author"}, format="json"
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "member_is_emergency"


def test_a_person_responsible_for_a_stage_keeps_a_role_that_decides(world):
    from apps.workflows import services as workflows

    with organization_context(world["org"]):
        workflows.save_template(
            None,
            actor=world["admin"],
            name="مسار",
            is_default=True,
            stages=[{"name": "مراجعة", "assignee_user": world["reviewer"].pk, "due_work_days": 2}],
        )
    reviewer = Membership.all_organizations.get(user=world["reviewer"])
    refused = signed_in("admin@a.test").patch(
        f"/api/organizations/current/members/{reviewer.pk}/", {"role": "author"}, format="json"
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "member_assigned_to_stage"
    # Another role that decides is fine.
    assert (
        signed_in("admin@a.test")
        .patch(f"/api/organizations/current/members/{reviewer.pk}/", {"role": "approver"}, format="json")
        .status_code
        == 200
    )


def test_a_forgotten_password_gets_a_link_and_the_answer_never_says_who_has_an_account(world):
    known = APIClient().post("/api/auth/password/forgot/", {"email": "Author@a.test"}, format="json")
    unknown = APIClient().post("/api/auth/password/forgot/", {"email": "nobody@a.test"}, format="json")
    assert (known.status_code, unknown.status_code) == (202, 202) and known.json() == unknown.json()
    [message] = mail.outbox
    assert message.to == ["author@a.test"]
    uid, token = link_in(message)
    assert set_password(uid, token, "a-brand-new-password-3").status_code == 204
    old = APIClient().post("/api/auth/login/", {"email": "author@a.test", "password": PASSWORD}, format="json")
    new = APIClient().post(
        "/api/auth/login/", {"email": "author@a.test", "password": "a-brand-new-password-3"}, format="json"
    )
    assert (old.status_code, new.status_code) == (400, 200)


def test_a_link_with_a_wrong_token_or_person_is_refused(world):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    uid = urlsafe_base64_encode(force_bytes(world["author"].pk))
    assert set_password(uid, "wrong-token").json()["error"]["code"] == "password_link_invalid"
    token = default_token_generator.make_token(world["author"])
    other = urlsafe_base64_encode(force_bytes(world["reviewer"].pk))
    assert set_password(other, token).json()["error"]["code"] == "password_link_invalid"
    assert set_password("not-base64!", token).json()["error"]["code"] == "password_link_invalid"
