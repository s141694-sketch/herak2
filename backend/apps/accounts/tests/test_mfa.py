"""Two-factor authentication with TOTP (task 6.7, spec 7.1, D67): enrolment, the second step of a password
sign-in, the organization's requirement for admins and approvers, the emergency account, and a reset by an admin."""

import time

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.accounts import mfa
from apps.accounts.models import Membership, Organization, Role, TOTPDevice
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member
from apps.sso import services as sso
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "x" * 12


@pytest.fixture
def world():
    org = Organization.objects.create(name="مركز", slug="vtc")
    with organization_context(org):
        people = {
            "admin": member("admin@vtc.test", Role.ADMIN),
            "approver": member("approver@vtc.test", Role.APPROVER),
            "author": member("author@vtc.test", Role.AUTHOR),
        }
    for user in people.values():
        user.set_password(PASSWORD)
        user.save()
    return {"org": org, **people}


def password(client, email):
    return client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")


def enrol(client):
    """Enrols the signed-in person and returns their TOTP generator."""
    started = client.post("/api/auth/mfa/enrol/").json()
    assert started["otpauth_uri"].startswith("otpauth://totp/") and "secret=" in started["otpauth_uri"]
    totp = pyotp.TOTP(started["secret"])
    assert client.post("/api/auth/mfa/confirm/", {"code": totp.now()}, format="json").status_code == 200
    return totp


def next_code(totp):
    """A code for the next time step, so it was not used yet."""
    return totp.at(time.time() + 30)


def test_enrolment_is_confirmed_with_a_code_and_the_secret_is_stored_encrypted(world):
    client = APIClient()
    password(client, "author@vtc.test")
    started = client.post("/api/auth/mfa/enrol/").json()
    assert (
        client.post("/api/auth/mfa/confirm/", {"code": "000000"}, format="json").json()["error"]["code"]
        == "mfa_code_invalid"
    )
    totp = pyotp.TOTP(started["secret"])
    assert client.post("/api/auth/mfa/confirm/", {"code": totp.now()}, format="json").status_code == 200
    device = TOTPDevice.objects.get(user=world["author"])
    assert device.confirmed_at is not None and started["secret"] not in device.secret_encrypted
    assert client.get("/api/auth/me/").json()["user"]["mfa_enabled"] is True
    assert client.post("/api/auth/mfa/enrol/").json()["error"]["code"] == "mfa_already_enabled"


def test_a_password_sign_in_then_asks_for_the_code(world):
    client = APIClient()
    password(client, "author@vtc.test")
    totp = enrol(client)
    client.post("/api/auth/logout/")

    client = APIClient()
    first = password(client, "author@vtc.test").json()
    assert first == {"mfa_required": True}
    assert client.get("/api/auth/me/").status_code in (401, 403)  # not signed in yet
    assert (
        client.post("/api/auth/mfa/verify/", {"code": "123456"}, format="json").json()["error"]["code"]
        == "mfa_code_invalid"
    )
    done = client.post("/api/auth/mfa/verify/", {"code": next_code(totp)}, format="json")
    assert done.status_code == 200 and done.json()["user"]["email"] == "author@vtc.test"
    assert done.json()["organization"]["id"] == world["org"].pk


def test_a_code_is_accepted_once(world):
    client = APIClient()
    password(client, "author@vtc.test")
    totp = enrol(client)
    code = next_code(totp)
    for attempt in range(2):
        client = APIClient()
        password(client, "author@vtc.test")
        status = client.post("/api/auth/mfa/verify/", {"code": code}, format="json").status_code
        assert status == (200 if attempt == 0 else 409)


def test_too_many_wrong_codes_end_the_attempt(world):
    client = APIClient()
    password(client, "author@vtc.test")
    totp = enrol(client)
    client = APIClient()
    password(client, "author@vtc.test")
    for _ in range(mfa.MAX_ATTEMPTS):
        client.post("/api/auth/mfa/verify/", {"code": "000000"}, format="json")
    late = client.post("/api/auth/mfa/verify/", {"code": next_code(totp)}, format="json")
    assert late.json()["error"]["code"] == "mfa_not_pending"  # back to the password


def test_an_organization_may_require_it_of_admins_and_approvers(world):
    world["org"].mfa_required_for_managers = True
    world["org"].save()
    approver = APIClient()
    body = password(approver, "approver@vtc.test").json()
    # Signed in, but the organization is closed until the second factor is set up.
    assert body["organization"] is None and body["memberships"][0]["mfa_required"] is True
    assert approver.get("/api/organizations/current/").json()["error"]["code"] == "no_active_organization"
    enrol(approver)  # confirming also checks the second factor for this session
    assert (
        approver.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json").status_code
        == 200
    )
    author = APIClient()
    assert password(author, "author@vtc.test").json()["organization"]["id"] == world["org"].pk  # not a manager


def test_the_emergency_account_signs_in_with_password_and_code_under_enforcement(world, settings):
    with organization_context(world["org"]):
        config = sso.save_provider(
            None, actor=world["admin"], issuer="https://idp.vtc.test", client_id="c", client_secret="s"
        )
        IdentityProviderConfig.objects.filter(pk=config.pk).update(
            discovery_ok_at=config.config_changed_at, test_login_ok_at=config.config_changed_at
        )
        config.refresh_from_db()
        with pytest.raises(sso.SsoError) as unprotected:
            sso.set_policy(config, actor=world["admin"], enabled=True, enforced=True, emergency_user=world["admin"])
        assert unprotected.value.get_codes() == "emergency_account_needs_mfa"
    admin = APIClient()
    password(admin, "admin@vtc.test")
    totp = enrol(admin)
    with organization_context(world["org"]):
        sso.set_policy(config, actor=world["admin"], enabled=True, enforced=True, emergency_user=world["admin"])

    emergency = APIClient()
    assert password(emergency, "admin@vtc.test").json() == {"mfa_required": True}
    signed_in = emergency.post("/api/auth/mfa/verify/", {"code": next_code(totp)}, format="json").json()
    assert signed_in["organization"]["id"] == world["org"].pk  # the one password that still opens it
    other_admin = APIClient()
    assert password(other_admin, "approver@vtc.test").json()["error"]["code"] == "sso_required"


def test_turning_it_off_needs_a_code_and_is_refused_where_it_is_required(world):
    world["org"].mfa_required_for_managers = True
    world["org"].save()
    admin = APIClient()
    password(admin, "admin@vtc.test")
    totp = enrol(admin)
    assert (
        admin.post("/api/auth/mfa/disable/", {"code": next_code(totp)}, format="json").json()["error"]["code"]
        == "mfa_required"
    )
    world["org"].mfa_required_for_managers = False
    world["org"].save()
    assert admin.post("/api/auth/mfa/disable/", {"code": "000000"}, format="json").status_code == 409
    assert admin.post("/api/auth/mfa/disable/", {"code": next_code(totp)}, format="json").status_code == 204
    assert not TOTPDevice.objects.filter(user=world["admin"]).exists()


def test_an_admin_resets_a_members_lost_second_factor(world):
    author = APIClient()
    password(author, "author@vtc.test")
    enrol(author)
    admin = APIClient()
    password(admin, "admin@vtc.test")
    membership = Membership.all_organizations.get(user=world["author"])
    anonymous = APIClient().post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/")
    assert anonymous.status_code in (401, 403, 409)
    assert admin.post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/").status_code == 204
    assert not TOTPDevice.objects.filter(user=world["author"]).exists()
    with organization_context(world["org"]):
        assert AuditLog.objects.filter(event="mfa.reset", actor=world["admin"]).exists()
    approver = APIClient()
    password(approver, "approver@vtc.test")
    assert approver.post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/").status_code == 403


def test_a_second_factor_also_used_in_another_organization_is_not_reset_by_one_of_them(world):
    other = Organization.objects.create(name="أخرى", slug="other")
    with organization_context(other):
        Membership.objects.create(user=world["author"], role=Role.REVIEWER)
    author = APIClient()
    password(author, "author@vtc.test")
    author.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json")
    enrol(author)
    admin = APIClient()
    password(admin, "admin@vtc.test")
    membership = Membership.all_organizations.get(user=world["author"], organization=world["org"])
    refused = admin.post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/")
    assert refused.json()["error"]["code"] == "mfa_reset_other_organizations"
