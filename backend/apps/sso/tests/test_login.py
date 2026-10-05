"""Signing in through the organization's provider (tasks 6.5, 6.6; spec 7.2): email, domain, provider, back.

A fake provider signs real ID tokens with an RSA key, so the checks run as they do against a real one (the
Keycloak tests in test_keycloak.py run the same flow end to end)."""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member
from apps.sso import login as sso_login
from apps.sso import services
from apps.sso.models import ExternalIdentity, IdentityProviderConfig, VerifiedDomain
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
ISSUER = "https://idp.vtc.test/realms/vtc"
KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})


class FakeProvider:
    """Discovery, keys and the token endpoint of one provider; ``claims`` shape the next ID token."""

    def __init__(self):
        self.claims: dict = {}
        self.key = KEY
        self.down = False
        self.last_token_request: dict | None = None

    def fetch_json(self, url):
        if self.down:
            raise services.requests.ConnectionError("provider down")
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/certs",
            }
        return {"keys": [KEY.as_dict(private=False)]}

    def exchange(self, meta, config, code, verifier, redirect_uri):
        self.last_token_request = {"code": code, "verifier": verifier, "redirect_uri": redirect_uri}
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": config.client_id,
            "sub": "subject-1",
            "iat": now,
            "exp": now + 300,
            "email": "noura@vtc.test",
            "email_verified": True,
            "name": "نورة البلوشية",
            "nonce": self.nonce,
            **self.claims,
        }
        return {"id_token": jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, self.key)}


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(services, "fetch_json", fake.fetch_json)
    monkeypatch.setattr(sso_login, "exchange_code", fake.exchange)
    return fake


@pytest.fixture
def world():
    org = Organization.objects.create(name="مركز", slug="vtc", sso_session_hours=4)
    other = Organization.objects.create(name="أخرى", slug="other")
    with organization_context(org):
        admin = member("admin@vtc.test", Role.ADMIN)
        admin.set_password("x" * 12)
        admin.save()
        config = services.save_provider(None, actor=admin, issuer=ISSUER, client_id="harak2", client_secret="s")
        VerifiedDomain.objects.create(domain="vtc.test", token="t", verified_at="2026-10-05T00:00Z", created_by=admin)
        IdentityProviderConfig.objects.filter(pk=config.pk).update(enabled=True)
    return {"org": org, "other": other, "admin": admin, "config": config}


def start(client, email, provider, **extra):
    response = client.post("/api/auth/sso/start/", {"email": email, **extra}, format="json")
    if response.status_code == 200:
        query = parse_qs(urlparse(response.json()["redirect"]).query)
        provider.nonce = query["nonce"][0]
        return response, query
    return response, None


def back(client, query, **params):
    return client.get("/api/auth/sso/callback/", {"code": "the-code", "state": query["state"][0], **params})


def error_of(response):
    assert response.status_code == 302
    location = urlparse(response["Location"])
    return parse_qs(location.query).get("sso_error", [None])[0]


def test_the_email_domain_leads_to_the_organizations_provider(world, provider):
    client = APIClient()
    response, query = start(client, "Noura@VTC.test", provider)
    assert response.status_code == 200
    redirect = urlparse(response.json()["redirect"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == f"{ISSUER}/auth"
    assert query["client_id"] == ["harak2"] and query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"] and query["login_hint"] == ["noura@vtc.test"]
    assert "openid" in query["scope"][0].split()


@pytest.mark.parametrize("email", ["noura@elsewhere.test", "not-an-email", ""])
def test_without_a_verified_domain_and_provider_there_is_no_single_sign_on(world, provider, email):
    response, _ = start(APIClient(), email, provider)
    assert response.status_code == 409 and response.json()["error"]["code"] == "sso_not_available"


def test_a_disabled_provider_is_not_offered(world, provider):
    IdentityProviderConfig.all_organizations.filter(pk=world["config"].pk).update(enabled=False)
    response, _ = start(APIClient(), "noura@vtc.test", provider)
    assert response.json()["error"]["code"] == "sso_not_available"


def test_a_provider_that_cannot_be_reached_says_so(world, provider):
    provider.down = True
    response, _ = start(APIClient(), "noura@vtc.test", provider)
    assert response.status_code == 503 and response.json()["error"]["code"] == "provider_unavailable"


def test_the_first_sign_in_creates_a_pending_member_in_the_organization(world, provider):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    response = back(client, query)
    assert error_of(response) is None and response["Location"].endswith("/")
    user = User.objects.get(email="noura@vtc.test")
    assert user.full_name == "نورة البلوشية" and not user.has_usable_password()
    membership = Membership.all_organizations.get(user=user)
    assert (membership.organization, membership.role) == (world["org"], Role.PENDING)
    assert ExternalIdentity.all_organizations.get(user=user).subject == "subject-1"
    me = client.get("/api/auth/me/").json()
    assert me["user"]["email"] == "noura@vtc.test" and me["organization"]["id"] == world["org"].pk
    assert client.session.get_expiry_age() == 4 * 3600  # the organization's session length (D68)
    assert provider.last_token_request["verifier"] and provider.last_token_request["code"] == "the-code"
    assert AuditLog.all_organizations.filter(event="sso.login", actor=user).exists()


def test_an_existing_account_is_linked_and_keeps_its_other_memberships(world, provider):
    with organization_context(world["other"]):
        existing = member("noura@vtc.test", Role.AUTHOR)
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    back(client, query)
    roles = dict(Membership.all_organizations.filter(user=existing).values_list("organization__slug", "role"))
    assert roles == {"other": Role.AUTHOR, "vtc": Role.PENDING}


def test_a_known_identity_is_found_by_its_subject_even_after_an_email_change(world, provider):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    back(client, query)
    client = APIClient()
    provider.claims = {"email": "noura.b@vtc.test"}
    _, query = start(client, "noura.b@vtc.test", provider)
    back(client, query)
    assert client.get("/api/auth/me/").json()["user"]["email"] == "noura@vtc.test"
    assert User.objects.filter(email__endswith="@vtc.test").count() == 2  # the admin and noura


@pytest.mark.parametrize(
    "claims,code",
    [
        ({"email_verified": False}, "sso_email_unverified"),
        ({"email": "noura@elsewhere.test"}, "sso_domain_not_allowed"),
        ({"aud": "someone-else"}, "sso_token_invalid"),
        ({"iss": "https://evil.test"}, "sso_token_invalid"),
        ({"exp": int(time.time()) - 600}, "sso_token_invalid"),
        ({"nonce": "replayed"}, "sso_token_invalid"),
    ],
)
def test_an_identity_the_rules_refuse_signs_nobody_in(world, provider, claims, code):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    provider.claims = claims
    assert error_of(back(client, query)) == code
    assert client.get("/api/auth/me/").status_code in (401, 403)
    assert not User.objects.filter(email="noura@vtc.test").exists()


def test_a_token_signed_by_another_key_is_refused(world, provider):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    provider.key = OTHER_KEY
    assert error_of(back(client, query)) == "sso_token_invalid"


def test_the_state_must_be_the_one_this_browser_was_given(world, provider):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    assert error_of(client.get("/api/auth/sso/callback/", {"code": "c", "state": "forged"})) == "sso_state_invalid"
    # Used once: replaying the right state after the flow ended fails too.
    back(client, query)
    assert error_of(back(client, query)) == "sso_state_invalid"


def test_a_refusal_at_the_provider_is_reported(world, provider):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    response = client.get("/api/auth/sso/callback/", {"state": query["state"][0], "error": "access_denied"})
    assert error_of(response) == "sso_denied"


def test_an_admins_test_sign_in_proves_the_provider_without_switching_the_session(world, provider):
    admin = APIClient()
    admin.post("/api/auth/login/", {"email": "admin@vtc.test", "password": "x" * 12}, format="json")
    IdentityProviderConfig.all_organizations.filter(pk=world["config"].pk).update(enabled=False)
    response = admin.post(f"/api/sso/providers/{world['config'].pk}/test-login/")
    query = parse_qs(urlparse(response.json()["redirect"]).query)
    provider.nonce = query["nonce"][0]
    done = back(admin, query)
    assert "sso_test=ok" in done["Location"]
    assert admin.get("/api/auth/me/").json()["user"]["email"] == "admin@vtc.test"
    config = IdentityProviderConfig.all_organizations.get(pk=world["config"].pk)
    assert config.test_login_ok_at is not None
    assert not User.objects.filter(email="noura@vtc.test").exists()  # nobody was signed in or created
