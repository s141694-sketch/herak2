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
        == "mfa_disable_required"
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


# --- From the independent review of phase 6 -----------------------------------------------------------------


def test_a_second_factor_checked_for_one_person_does_not_carry_over_to_the_next_sign_in(world):
    world["org"].mfa_required_for_managers = True
    world["org"].save()
    browser = APIClient()
    password(browser, "author@vtc.test")
    enrol(browser)  # the author's own factor, checked in this browser
    body = password(browser, "admin@vtc.test").json()  # the admin has no factor
    assert body["organization"] is None and body["memberships"][0]["mfa_required"] is True
    assert browser.get("/api/organizations/current/").status_code == 409


def test_the_emergency_accounts_factor_is_not_reset_while_it_is_the_emergency_account(world):
    with organization_context(world["org"]):
        config = sso.save_provider(
            None, actor=world["admin"], issuer="https://idp.vtc.test", client_id="c", client_secret="s"
        )
        IdentityProviderConfig.objects.filter(pk=config.pk).update(
            discovery_ok_at=config.config_changed_at, test_login_ok_at=config.config_changed_at
        )
        config.refresh_from_db()
        second = member("second@vtc.test", Role.ADMIN)
    second.set_password(PASSWORD)
    second.save()
    emergency = APIClient()
    password(emergency, "second@vtc.test")
    enrol(emergency)
    with organization_context(world["org"]):
        sso.set_policy(config, actor=world["admin"], enabled=True, enforced=True, emergency_user=second)
    admin = APIClient()
    admin.force_login(world["admin"])  # as if through the provider: a password no longer opens it
    from apps.tenancy.middleware import SESSION_KEY, mark_sso

    session = admin.session
    mark_sso(session, world["org"].pk, time.time() + 3600)
    session[SESSION_KEY] = world["org"].pk
    session.save()
    membership = Membership.all_organizations.get(user=second)
    refused = admin.post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "mfa_reset_emergency"
    assert TOTPDevice.objects.filter(user=second).exists()


def test_an_admin_does_not_reset_their_own_second_factor(world):
    admin = APIClient()
    password(admin, "admin@vtc.test")
    enrol(admin)
    membership = Membership.all_organizations.get(user=world["admin"])
    refused = admin.post(f"/api/organizations/current/members/{membership.pk}/reset-mfa/")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "mfa_reset_self"


def test_an_admin_signed_in_through_the_provider_may_require_a_second_factor_of_managers(world):
    from apps.tenancy.middleware import SESSION_KEY, SESSION_SSO_ONLY, mark_sso

    admin = APIClient()
    admin.force_login(world["admin"])
    session = admin.session
    mark_sso(session, world["org"].pk, time.time() + 3600)
    session[SESSION_SSO_ONLY] = True
    session[SESSION_KEY] = world["org"].pk
    session.save()
    response = admin.patch("/api/organizations/current/", {"mfa_required_for_managers": True}, format="json")
    assert response.status_code == 200 and response.json()["mfa_required_for_managers"] is True


def test_wrong_codes_are_counted_per_person_and_lock_the_factor_even_across_new_sign_ins(world):
    author = APIClient()
    password(author, "author@vtc.test")
    totp = enrol(author)
    from django.core.cache import cache

    attacker = APIClient()
    for _ in range(mfa.MAX_FAILURES):
        cache.clear()  # as if from many addresses: the rate limit per address does not stop this
        assert password(attacker, "author@vtc.test").json() == {"mfa_required": True}  # a fresh attempt each time
        attacker.post("/api/auth/mfa/verify/", {"code": "000000"}, format="json")
    password(attacker, "author@vtc.test")
    locked = attacker.post("/api/auth/mfa/verify/", {"code": next_code(totp)}, format="json")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "mfa_locked"
    # The lock passes with time; the right code then works, and the count starts again.
    TOTPDevice.objects.filter(user=world["author"]).update(locked_until=None)
    password(attacker, "author@vtc.test")
    assert attacker.post("/api/auth/mfa/verify/", {"code": next_code(totp)}, format="json").status_code == 200
    assert TOTPDevice.objects.get(user=world["author"]).failures == 0


def test_turning_it_off_counts_wrong_codes_too(world):
    author = APIClient()
    password(author, "author@vtc.test")
    totp = enrol(author)
    for _ in range(mfa.MAX_FAILURES):
        author.post("/api/auth/mfa/disable/", {"code": "000000"}, format="json")
    locked = author.post("/api/auth/mfa/disable/", {"code": next_code(totp)}, format="json")
    assert locked.json()["error"]["code"] == "mfa_locked"
    assert TOTPDevice.objects.filter(user=world["author"]).exists()


def test_a_code_typed_in_arabic_indic_digits_is_read_as_the_same_code(world):
    author = APIClient()
    password(author, "author@vtc.test")
    totp = enrol(author)
    arabic = next_code(totp).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    signing_in = APIClient()
    password(signing_in, "author@vtc.test")
    assert signing_in.post("/api/auth/mfa/verify/", {"code": arabic}, format="json").status_code == 200
    other = APIClient()
    password(other, "author@vtc.test")
    assert other.post("/api/auth/mfa/verify/", {"code": "١٢٣٤٥"}, format="json").status_code == 409  # not six


@pytest.mark.django_db(transaction=True)
def test_an_enrolment_restarted_while_one_is_confirmed_does_not_confirm_an_unchecked_secret(world, monkeypatch):
    import threading

    from django.db import connection

    client = APIClient()
    password(client, "author@vtc.test")
    started = client.post("/api/auth/mfa/enrol/").json()
    checked = threading.Event()
    real_accept = mfa._accept

    def slow_accept(device, code):
        accepted = real_accept(device, code)
        checked.set()
        time.sleep(0.5)  # the other request arrives while this one still holds the device
        return accepted

    monkeypatch.setattr(mfa, "_accept", slow_accept)
    outcome = {}

    def restart():
        checked.wait(5)
        try:
            outcome["restart"] = mfa.begin_enrolment(world["author"])
        except mfa.MfaError as exc:
            outcome["restart"] = exc.get_codes()
        finally:
            connection.close()

    other = threading.Thread(target=restart)
    other.start()
    assert (
        client.post("/api/auth/mfa/confirm/", {"code": pyotp.TOTP(started["secret"]).now()}, format="json").status_code
        == 200
    )
    other.join()
    assert outcome["restart"] == "mfa_already_enabled"
    device = TOTPDevice.objects.get(user=world["author"])
    from apps.core import secrets

    assert device.confirmed_at is not None and secrets.decrypt(device.secret_encrypted) == started["secret"]


def test_an_expired_code_is_refused(world):
    author = APIClient()
    password(author, "author@vtc.test")
    totp = enrol(author)
    signing_in = APIClient()
    password(signing_in, "author@vtc.test")
    expired = signing_in.post("/api/auth/mfa/verify/", {"code": totp.at(time.time() - 90)}, format="json")
    assert expired.status_code == 409 and expired.json()["error"]["code"] == "mfa_code_invalid"


def test_admins_see_which_members_have_a_second_factor_and_others_do_not(world):
    author = APIClient()
    password(author, "author@vtc.test")
    enrol(author)
    admin = APIClient()
    password(admin, "admin@vtc.test")
    listed = {m["user"]["email"]: m["mfa_enabled"] for m in admin.get("/api/organizations/current/members/").json()}
    assert listed == {"admin@vtc.test": False, "approver@vtc.test": False, "author@vtc.test": True}
    assert all("mfa_enabled" not in m for m in author.get("/api/organizations/current/members/").json())
