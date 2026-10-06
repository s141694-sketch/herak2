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
        self.alg = "RS256"
        self.down = False
        self.keys_down = False
        self.token_down = False
        self.meta: dict = {}
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
                **self.meta,
            }
        if self.keys_down:
            raise services.requests.ConnectionError("keys unreachable")
        return {"keys": [KEY.as_dict(private=False)]}

    def exchange(self, meta, config, code, verifier, redirect_uri):
        if self.token_down:
            raise services.requests.ConnectionError("token endpoint unreachable")
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
        return {"id_token": jwt.encode({"alg": self.alg, "kid": "test-key"}, claims, self.key, algorithms=[self.alg])}


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
    assert abs(client.session.get_expiry_age() - 4 * 3600) <= 2  # the organization's session length (D68)
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


# --- From the independent review of phase 6 -----------------------------------------------------------------


def signed_in(client, provider, email="noura@vtc.test"):
    _, query = start(client, email, provider)
    response = back(client, query)
    assert error_of(response) is None, response["Location"]
    return client


def test_the_session_length_is_a_deadline_that_later_requests_do_not_move(world, provider):
    from django.contrib.sessions.models import Session

    client = signed_in(APIClient(), provider)
    key = client.cookies["sessionid"].value
    expires = Session.objects.get(session_key=key).expire_date
    time.sleep(1.1)
    assert (
        client.post("/api/auth/switch-organization/", {"organization_id": world["org"].pk}, format="json").status_code
        == 200
    )
    assert Session.objects.get(session_key=key).expire_date == expires


def test_past_its_deadline_the_single_sign_on_no_longer_opens_the_organization(world, provider):
    from apps.tenancy.middleware import SESSION_SSO

    client = signed_in(APIClient(), provider)
    session = client.session
    session[SESSION_SSO] = {str(world["org"].pk): time.time() - 1}
    session.save()
    me = client.get("/api/auth/me/").json()
    assert me["organization"] is None


def test_platform_staff_accounts_never_sign_in_through_a_tenants_provider(world, provider):
    User.objects.create_superuser(email="noura@vtc.test", password="y" * 12)
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    assert error_of(back(client, query)) == "sso_account_not_allowed"
    assert client.get("/api/auth/me/").status_code in (401, 403)
    assert not ExternalIdentity.all_organizations.exists()


def test_a_deactivated_account_is_told_so_and_nothing_is_written(world, provider):
    User.objects.create_user(email="noura@vtc.test", password=None, is_active=False)
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    assert error_of(back(client, query)) == "sso_account_disabled"
    assert not ExternalIdentity.all_organizations.exists()
    assert not Membership.all_organizations.filter(user__email="noura@vtc.test").exists()
    assert not AuditLog.all_organizations.filter(event="sso.login").exists()


def test_a_flow_started_before_the_provider_was_disabled_signs_nobody_in(world, provider):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    IdentityProviderConfig.all_organizations.filter(pk=world["config"].pk).update(enabled=False)
    assert error_of(back(client, query)) == "sso_not_available"
    assert client.get("/api/auth/me/").status_code in (401, 403)


@pytest.mark.parametrize("where", ["keys_down", "token_down"])
def test_a_provider_that_fails_during_the_return_is_reported_as_unavailable(world, provider, where):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    setattr(provider, where, True)
    assert error_of(back(client, query)) == "provider_unavailable"


@pytest.mark.parametrize("alg", ["PS256", "RS512"])
def test_stronger_rsa_signatures_are_accepted(world, provider, alg):
    provider.alg = alg
    signed_in(APIClient(), provider)


def test_a_symmetric_signature_is_never_accepted(world, provider):
    from joserfc.jwk import OctKey

    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    provider.alg, provider.key = "HS256", OctKey.import_key("x" * 32)
    assert error_of(back(client, query)) == "sso_token_invalid"


@pytest.mark.parametrize(
    "endpoint",
    ["javascript:alert(document.domain)//", "data:text/html,x", "//idp.vtc.test/auth", "ftp://idp.vtc.test/auth"],
)
def test_a_discovery_document_with_an_endpoint_that_is_not_https_is_refused(world, provider, endpoint):
    provider.meta = {"authorization_endpoint": endpoint}
    response, _ = start(APIClient(), "noura@vtc.test", provider)
    assert response.status_code == 503 and response.json()["error"]["code"] == "provider_unavailable"


def test_two_first_sign_ins_at_once_both_end_signed_in(world, provider, monkeypatch):
    """The second one finds the account the first one created between its look-up and its insert."""
    real_filter = User.objects.filter

    def stale(*args, **kwargs):
        if kwargs.get("email__iexact") == "noura@vtc.test" and not real_filter(email="noura@vtc.test").exists():
            User.objects.create_user(email="noura@vtc.test", password=None)  # the other sign-in got there first
            return User.objects.none()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(User.objects, "filter", stale)
    signed_in(APIClient(), provider)
    monkeypatch.undo()
    assert User.objects.filter(email="noura@vtc.test").count() == 1


@pytest.mark.parametrize(
    "claims,code",
    [
        ({"email_verified": False}, "sso_test_email_unverified"),
        ({"email": "a@elsewhere.test"}, "sso_test_domain_not_allowed"),
    ],
)
def test_a_test_sign_in_with_an_identity_members_could_not_use_does_not_count(world, provider, claims, code):
    admin = APIClient()
    admin.post("/api/auth/login/", {"email": "admin@vtc.test", "password": "x" * 12}, format="json")
    response = admin.post(f"/api/sso/providers/{world['config'].pk}/test-login/")
    query = parse_qs(urlparse(response.json()["redirect"]).query)
    provider.nonce = query["nonce"][0]
    provider.claims = claims
    assert f"sso_test={code}" in back(admin, query)["Location"]
    assert IdentityProviderConfig.all_organizations.get(pk=world["config"].pk).test_login_ok_at is None


def test_microsoft_entra_ids_verified_email_claim_is_accepted_in_place_of_email_verified(world, provider):
    """Entra ID tokens carry no email_verified; its optional xms_edov claim says the same (spec 7.2 covers Entra)."""
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    provider.claims = {"email_verified": None, "xms_edov": True}
    assert error_of(back(client, query)) is None


@pytest.mark.parametrize("claims", [{"xms_edov": False}, {}])
def test_without_either_claim_the_email_is_not_trusted(world, provider, claims):
    client = APIClient()
    _, query = start(client, "noura@vtc.test", provider)
    provider.claims = {"email_verified": None, **claims}
    assert error_of(back(client, query)) == "sso_email_unverified"


@pytest.mark.parametrize("language,expected", [("en", ["en"]), ("ar", ["ar"]), ("fr", None), (3, None)])
def test_the_interface_language_is_passed_to_the_provider_when_it_is_one_of_harakss(
    world, provider, language, expected
):
    response, query = start(APIClient(), "noura@vtc.test", provider, language=language)
    assert response.status_code == 200
    assert query.get("ui_locales") == expected


def test_a_browser_already_signed_in_is_told_on_its_own_page_why_the_provider_refused(world, provider):
    with organization_context(world["org"]):
        signed = member("signed@vtc.test", Role.AUTHOR)
    client = APIClient()
    client.force_login(signed)
    response, query = start(client, "noura@vtc.test", provider)
    refused = client.get("/api/auth/sso/callback/", {"state": query["state"][0], "error": "access_denied"})
    assert urlparse(refused["Location"]).path == "/" and error_of(refused) == "sso_denied"
    stale = client.get("/api/auth/sso/callback/", {"state": "old", "code": "c"})
    assert urlparse(stale["Location"]).path == "/" and error_of(stale) == "sso_state_invalid"


def test_an_admins_test_sign_in_that_expired_returns_to_the_security_settings(world, provider):
    admin = APIClient()
    admin.post("/api/auth/login/", {"email": "admin@vtc.test", "password": "x" * 12}, format="json")
    admin.post(f"/api/sso/providers/{world['config'].pk}/test-login/")
    stale = admin.get("/api/auth/sso/callback/", {"state": "old", "code": "c"})
    location = urlparse(stale["Location"])
    assert location.path == "/settings/security" and parse_qs(location.query)["sso_test"] == ["sso_state_invalid"]


@pytest.mark.parametrize(
    "email,available", [("Noura@VTC.test", True), ("noura@elsewhere.test", False), ("not-an-email", False)]
)
def test_the_sign_in_page_learns_from_the_email_whether_its_organization_has_a_provider(
    world, provider, email, available
):
    """Spec 7.2: email, then its domain, then the organization's provider. Nothing is started or written."""
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf/")
    token = client.cookies["csrftoken"].value
    response = client.post("/api/auth/sso/discover/", {"email": email}, format="json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 200 and response.json() == {"available": available}
    assert "sso_flow" not in client.session
