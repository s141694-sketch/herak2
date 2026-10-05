"""Single sign-on end to end on a real Keycloak (spec 8.1 item 6; D62): the provider test, the first sign-in, the
refusals, and enforcement. Runs where KEYCLOAK_URL is set (CI, and the local runner in infra/keycloak)."""

import html
import os
import re
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.programs.tests.factories import member
from apps.sso import services
from apps.sso.models import IdentityProviderConfig, VerifiedDomain
from apps.tenancy.context import organization_context

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "").rstrip("/")
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not KEYCLOAK, reason="needs a Keycloak: set KEYCLOAK_URL (see infra/keycloak)"),
]
PASSWORD = "harak-sso-test"  # the realms' test fixture password (infra/keycloak/README.md)


@pytest.fixture
def world(settings):
    settings.SSO_ALLOW_HTTP_ISSUERS = True  # the local Keycloak serves plain http
    org = Organization.objects.create(name="مركز التدريب المهني", slug="vtc")
    with organization_context(org):
        admin = member("admin@vtc.test", Role.ADMIN)
        admin.set_password("x" * 12)
        admin.save()
        config = services.save_provider(
            None,
            actor=admin,
            issuer=f"{KEYCLOAK}/realms/vtc",
            client_id="harak2",
            client_secret="vtc-test-client-secret",
        )
        services.test_connection(config, actor=admin)
        VerifiedDomain.objects.create(domain="vtc.test", token="t", verified_at="2026-10-05T00:00Z", created_by=admin)
        config = services.set_policy(IdentityProviderConfig.objects.get(), actor=admin, enabled=True)
    return {"org": org, "admin": admin, "config": config}


def keycloak_login(redirect: str, username: str) -> dict:
    """Signs in on Keycloak's own page as a browser would, and returns the query it sends back to Harak."""
    browser = requests.Session()
    page = browser.get(redirect, timeout=15)
    action = html.unescape(re.search(r'action="([^"]+)"', page.text).group(1))
    # Keycloak marks its cookies Secure; browsers still send them to http://localhost, a secure context.
    jar = {c.name: c.value for c in browser.cookies}
    reply = browser.post(
        action, data={"username": username, "password": PASSWORD}, cookies=jar, allow_redirects=False, timeout=15
    )
    assert reply.status_code in (302, 303), reply.text[:300]
    return {key: values[0] for key, values in parse_qs(urlparse(reply.headers["Location"]).query).items()}


def sign_in(client: APIClient, email: str, username: str):
    started = client.post("/api/auth/sso/start/", {"email": email}, format="json")
    assert started.status_code == 200, started.content
    query = keycloak_login(started.json()["redirect"], username)
    return client.get("/api/auth/sso/callback/", query)


def refusal(response) -> str | None:
    return parse_qs(urlparse(response["Location"]).query).get("sso_error", [None])[0]


def test_the_first_sign_in_makes_a_pending_member(world):
    client = APIClient()
    response = sign_in(client, "noura@vtc.test", "noura")
    assert refusal(response) is None, response["Location"]
    user = User.objects.get(email="noura@vtc.test")
    assert Membership.all_organizations.get(user=user).role == Role.PENDING
    assert client.get("/api/auth/me/").json()["organization"]["role"] == Role.PENDING


def test_an_unverified_email_and_a_domain_not_verified_are_refused(world):
    # The realm vouches for these people, but Harak does not let them in (spec 7.2, 7.7).
    assert refusal(sign_in(APIClient(), "ghost@vtc.test", "ghost")) == "sso_email_unverified"
    assert refusal(sign_in(APIClient(), "outsider@vtc.test", "outsider")) == "sso_domain_not_allowed"
    assert not User.objects.filter(email__in=["ghost@vtc.test", "outsider@elsewhere.test"]).exists()


def test_an_email_outside_any_verified_domain_has_no_single_sign_on(world):
    response = APIClient().post("/api/auth/sso/start/", {"email": "outsider@elsewhere.test"}, format="json")
    assert response.json()["error"]["code"] == "sso_not_available"


def test_with_enforcement_the_password_no_longer_opens_the_organization(world):
    with organization_context(world["org"]):
        hamed = member("hamed@vtc.test", Role.AUTHOR)
        hamed.set_password("x" * 12)
        hamed.save()
        IdentityProviderConfig.objects.filter(pk=world["config"].pk).update(
            test_login_ok_at=world["config"].config_changed_at
        )
        services.set_policy(
            IdentityProviderConfig.objects.get(),
            actor=world["admin"],
            enabled=True,
            enforced=True,
            emergency_user=world["admin"],
        )
    password = APIClient().post("/api/auth/login/", {"email": "hamed@vtc.test", "password": "x" * 12}, format="json")
    assert password.status_code == 409 and password.json()["error"]["code"] == "sso_required"
    client = APIClient()
    assert refusal(sign_in(client, "hamed@vtc.test", "hamed")) is None
    me = client.get("/api/auth/me/").json()
    assert (me["user"]["email"], me["organization"]["role"]) == ("hamed@vtc.test", Role.AUTHOR)
