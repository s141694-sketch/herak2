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
    # And may go to another organization and come back.
    client.post("/api/auth/switch-organization/", {"organization_id": world["other"].pk}, format="json")
    back_in = client.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json")
    assert back_in.status_code == 200


def test_the_policy_is_set_over_the_api_by_an_admin(world):
    mark_tested(world["config"])
    client, _ = password_login("admin@vtc.test")
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
