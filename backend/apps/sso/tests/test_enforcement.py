"""Enforcing single sign-on (task 6.6, D66): passwords no longer open the organization, except the emergency account;
it can only be turned on after the provider was tested."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role
from apps.core.errors import Conflict
from apps.programs.tests.factories import member
from apps.sso import services
from apps.sso.models import IdentityProviderConfig, VerifiedDomain
from apps.tenancy.context import organization_context

from .test_login import ISSUER, back, provider, start  # noqa: F401 - the provider fixture

pytestmark = pytest.mark.django_db
PASSWORD = "x" * 12


@pytest.fixture
def world():
    org = Organization.objects.create(name="مركز", slug="vtc")
    other = Organization.objects.create(name="أخرى", slug="other")
    with organization_context(org):
        admin = member("admin@vtc.test", Role.ADMIN)
        noura = member("noura@vtc.test", Role.AUTHOR)
        config = services.save_provider(None, actor=admin, issuer=ISSUER, client_id="harak2", client_secret="s")
        VerifiedDomain.objects.create(domain="vtc.test", token="t", verified_at="2026-10-05T00:00Z", created_by=admin)
    with organization_context(other):
        Membership.objects.create(user=noura, role=Role.REVIEWER)
    for user in (admin, noura):
        user.set_password(PASSWORD)
        user.save()
    return {"org": org, "other": other, "admin": admin, "noura": noura, "config": config}


def mark_tested(config):
    IdentityProviderConfig.all_organizations.filter(pk=config.pk).update(
        discovery_ok_at=config.config_changed_at, test_login_ok_at=config.config_changed_at
    )
    config.refresh_from_db()
    return config


def enforce(world):
    with_second_factor(world["admin"])
    with organization_context(world["org"]):
        return services.set_policy(
            mark_tested(world["config"]),
            actor=world["admin"],
            enabled=True,
            enforced=True,
            emergency_user=world["admin"],
        )


def password_login(email):
    client = APIClient()
    return client, client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")


def test_members_sign_in_through_the_provider_only_once_it_was_tested(world):
    with organization_context(world["org"]):
        with pytest.raises(Conflict) as untested:
            services.set_policy(world["config"], actor=world["admin"], enabled=True)
        assert untested.value.get_codes() == "provider_not_tested"
        IdentityProviderConfig.objects.filter(pk=world["config"].pk).update(
            discovery_ok_at=world["config"].config_changed_at
        )
        world["config"].refresh_from_db()
        assert services.set_policy(world["config"], actor=world["admin"], enabled=True).enabled


def test_enforcement_needs_a_test_sign_in_and_an_emergency_admin(world):
    with organization_context(world["org"]):
        config = world["config"]
        IdentityProviderConfig.objects.filter(pk=config.pk).update(discovery_ok_at=config.config_changed_at)
        config.refresh_from_db()
        with pytest.raises(Conflict) as untested:
            services.set_policy(
                config, actor=world["admin"], enabled=True, enforced=True, emergency_user=world["admin"]
            )
        assert untested.value.get_codes() == "provider_not_tested"
        config = mark_tested(config)
        with_second_factor(world["admin"])
        with pytest.raises(Conflict) as nobody:
            services.set_policy(config, actor=world["admin"], enabled=True, enforced=True)
        assert nobody.value.get_codes() == "emergency_account_required"
        with pytest.raises(Conflict) as not_admin:
            services.set_policy(
                config, actor=world["admin"], enabled=True, enforced=True, emergency_user=world["noura"]
            )
        assert not_admin.value.get_codes() == "emergency_account_invalid"


def test_with_enforcement_a_password_no_longer_opens_the_organization(world):
    enforce(world)
    client, response = password_login("noura@vtc.test")
    # Noura is also a member elsewhere: she signs in there; the enforcing organization is not open to a password.
    assert response.status_code == 200
    body = response.json()
    assert body["organization"]["id"] == world["other"].pk
    flags = {m["organization"]["slug"]: m["sso_required"] for m in body["memberships"]}
    assert flags == {"vtc": True, "other": False}
    switch = client.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json")
    assert switch.status_code == 409 and switch.json()["error"]["code"] == "sso_required"
    assert (
        client.post("/api/auth/switch-organization/", {"organization_id": world["other"].pk}, format="json").status_code
        == 200
    )


def test_a_member_of_the_enforcing_organization_only_is_told_to_use_single_sign_on(world):
    with organization_context(world["other"]):
        Membership.objects.filter(user=world["noura"]).delete()
    enforce(world)
    client, response = password_login("noura@vtc.test")
    assert response.status_code == 409 and response.json()["error"]["code"] == "sso_required"
    assert client.get("/api/auth/me/").status_code in (401, 403)


def test_a_password_session_opened_before_enforcement_loses_the_organization(world):
    client, _ = password_login("noura@vtc.test")
    client.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json")
    assert client.get("/api/organizations/current/").status_code == 200
    enforce(world)
    # The password session leaves the enforcing organization, for the one organization still open to it.
    assert client.get("/api/organizations/current/").json()["id"] == world["other"].pk


def test_a_single_sign_on_session_enters_the_enforcing_organization(world, provider):  # noqa: F811
    enforce(world)
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    back(client, query)
    assert client.get("/api/organizations/current/").json()["id"] == world["org"].pk
    # The provider vouches for her in its own organization only (D71): the other one wants her password.
    other = client.post("/api/auth/switch-organization/", {"organization_id": world["other"].pk}, format="json")
    assert other.status_code == 409 and other.json()["error"]["code"] == "password_required"
    flags = {
        m["organization"]["slug"]: m["password_required"] for m in client.get("/api/auth/me/").json()["memberships"]
    }
    assert flags == {"vtc": False, "other": True}
    # Her password in the same browser opens the other one, and the provider's sign-in still opens this one.
    client.post("/api/auth/login/", {"email": "noura@vtc.test", "password": PASSWORD}, format="json")
    assert (
        client.post("/api/auth/switch-organization/", {"organization_id": world["other"].pk}, format="json").status_code
        == 200
    )
    back_in = client.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json")
    assert back_in.status_code == 200


def test_an_organization_that_asks_for_its_provider_says_so_before_asking_for_a_second_factor(world):
    enforce(world)
    world["org"].mfa_required_for_managers = True
    world["org"].save()
    with organization_context(world["org"]):
        Membership.objects.filter(user=world["noura"]).update(role=Role.APPROVER)
    client, response = password_login("noura@vtc.test")
    flags = {m["organization"]["slug"]: (m["sso_required"], m["mfa_required"]) for m in response.json()["memberships"]}
    assert flags["vtc"] == (True, False)


def test_from_the_organization_list_a_member_starts_the_chosen_organizations_provider(world, provider):  # noqa: F811
    from urllib.parse import parse_qs, urlparse

    enforce(world)
    IdentityProviderConfig.all_organizations.filter(pk=world["config"].pk).update(enabled=True)
    with organization_context(world["other"]):
        outsider = member("x@elsewhere.test", Role.AUTHOR)
    with organization_context(world["org"]):
        Membership.objects.create(user=outsider, role=Role.AUTHOR)
    outsider.set_password(PASSWORD)
    outsider.save()
    client, _ = password_login("x@elsewhere.test")
    response = client.post("/api/auth/sso/start/", {"organization": world["org"].pk}, format="json")
    assert response.status_code == 200
    query = parse_qs(urlparse(response.json()["redirect"]).query)
    assert query["login_hint"] == ["x@elsewhere.test"] and query["client_id"] == ["harak2"]
    # Only for an organization of theirs that has a provider turned on.
    refused = client.post("/api/auth/sso/start/", {"organization": world["other"].pk}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "sso_not_available"
    anonymous = APIClient().post("/api/auth/sso/start/", {"organization": world["org"].pk}, format="json")
    assert anonymous.json()["error"]["code"] == "sso_not_available"


def test_the_policy_is_set_over_the_api_by_an_admin(world):
    mark_tested(world["config"])
    client, _ = password_login("admin@vtc.test")
    with_second_factor(world["admin"])  # after signing in: this session's second factor was not checked
    url = f"/api/sso/providers/{world['config'].pk}/policy/"
    assert client.post(url, {"enabled": "yes"}, format="json").status_code == 400
    noura, _ = password_login("noura@vtc.test")
    noura.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json")
    body = {"enabled": True, "enforced": True, "emergency_user": world["admin"].pk}
    assert noura.post(url, body, format="json").status_code == 403
    response = client.post(url, body, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["enforced"] is True and response.json()["emergency_user"]["id"] == world["admin"].pk
    # From now on the admin's own password session needs its second factor to enter (D66, task 6.7).
    assert client.get("/api/organizations/current/").json()["error"]["code"] == "no_active_organization"


def with_second_factor(user):
    """Gives a person a confirmed second factor, as the emergency account needs (spec 7.2)."""
    import pyotp
    from django.utils import timezone

    from apps.accounts.models import TOTPDevice
    from apps.core import secrets

    TOTPDevice.objects.update_or_create(
        user=user, defaults={"secret_encrypted": secrets.encrypt(pyotp.random_base32()), "confirmed_at": timezone.now()}
    )
    return user
