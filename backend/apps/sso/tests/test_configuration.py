"""An organization's single sign-on settings (tasks 6.3, 6.4): verified email domains and its OIDC provider."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.core.errors import Conflict
from apps.programs.tests.factories import member
from apps.sso import dns, services
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
PASSWORD = "x" * 12


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    other = Organization.objects.create(name="B", slug="b")
    with organization_context(org):
        admin = member("admin@example.com", Role.ADMIN)
        author = member("author@example.com", Role.AUTHOR)
    with organization_context(other):
        other_admin = member("other@example.com", Role.ADMIN)
    for user in (admin, author, other_admin):
        user.set_password(PASSWORD)
        user.save()
    return {"org": org, "other": other, "admin": admin, "author": author, "other_admin": other_admin}


@pytest.fixture
def txt(monkeypatch):
    """DNS answers the tests give: {record name: [TXT strings]}."""
    records: dict[str, list[str]] = {}

    def lookup(name):
        if name not in records:
            raise dns.LookupFailed("NXDOMAIN")
        return records[name]

    monkeypatch.setattr(dns, "txt_records", lookup)
    return records


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    return client


# --- Domains (task 6.3) ---------------------------------------------------------------------------------


@pytest.mark.parametrize("given,kept", [("VTC.Test", "vtc.test"), (" mail.vtc.test. ", "mail.vtc.test")])
def test_a_domain_is_kept_lowercase_without_a_trailing_dot(world, given, kept):
    with organization_context(world["org"]):
        assert services.add_domain(given, actor=world["admin"]).domain == kept


@pytest.mark.parametrize(
    "bad", ["", "localhost", "*.vtc.test", "vtc..test", "-vtc.test", "vtc.test/x", "a" * 250 + ".test", "user@vtc.test"]
)
def test_an_invalid_domain_is_refused(world, bad):
    with organization_context(world["org"]), pytest.raises(Conflict) as refused:
        services.add_domain(bad, actor=world["admin"])
    assert refused.value.get_codes() == "domain_invalid"


def test_a_domain_is_verified_by_its_txt_record(world, txt):
    with organization_context(world["org"]):
        domain = services.add_domain("vtc.test", actor=world["admin"])
        assert domain.record_name == "_harak2-verification.vtc.test"
        assert domain.record_value.startswith("harak2-verification=") and len(domain.token) >= 32
        with pytest.raises(Conflict) as missing:
            services.verify_domain(domain, actor=world["admin"])
        assert missing.value.get_codes() == "domain_record_missing"
        txt[domain.record_name] = ["v=spf1 -all", "harak2-verification=wrong"]
        with pytest.raises(Conflict):
            services.verify_domain(domain, actor=world["admin"])
        txt[domain.record_name] = ["v=spf1 -all", domain.record_value]
        verified = services.verify_domain(domain, actor=world["admin"])
        assert verified.verified_at is not None
        assert AuditLog.objects.filter(event="sso.domain_verified").exists()


def test_a_domain_verified_by_one_organization_cannot_be_verified_by_another(world, txt):
    with organization_context(world["org"]):
        mine = services.add_domain("vtc.test", actor=world["admin"])
        txt[mine.record_name] = [mine.record_value]
        services.verify_domain(mine, actor=world["admin"])
    with organization_context(world["other"]):
        theirs = services.add_domain("vtc.test", actor=world["other_admin"])
        txt[theirs.record_name] = [theirs.record_value]
        with pytest.raises(Conflict) as taken:
            services.verify_domain(theirs, actor=world["other_admin"])
        assert taken.value.get_codes() == "domain_taken"


# --- The identity provider (task 6.4) -------------------------------------------------------------------

PROVIDER = {"issuer": "https://login.vtc.test/realms/vtc", "client_id": "harak2", "client_secret": "s3cret"}


def test_the_client_secret_is_stored_encrypted_and_never_returned(world):
    admin = login("admin@example.com")
    created = admin.post("/api/sso/providers/", PROVIDER, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert "client_secret" not in body and body["has_secret"] is True
    with organization_context(world["org"]):
        config = IdentityProviderConfig.objects.get()
        assert "s3cret" not in config.client_secret_encrypted
        assert config.client_secret == "s3cret"
    # Leaving the secret out keeps it; giving one replaces it.
    admin.put(f"/api/sso/providers/{body['id']}/", {**PROVIDER, "client_secret": ""}, format="json")
    with organization_context(world["org"]):
        assert IdentityProviderConfig.objects.get().client_secret == "s3cret"


def test_only_an_admin_sees_or_changes_the_provider(world):
    author = login("author@example.com")
    assert author.get("/api/sso/providers/").status_code == 403
    assert author.post("/api/sso/providers/", PROVIDER, format="json").status_code == 403


@pytest.mark.parametrize(
    "change",
    [{"issuer": "http://login.vtc.test/realms/vtc"}, {"issuer": "not a url"}, {"client_id": ""}, {"client_secret": ""}],
)
def test_a_provider_needs_an_https_issuer_a_client_and_a_secret(world, change):
    admin = login("admin@example.com")
    response = admin.post("/api/sso/providers/", {**PROVIDER, **change}, format="json")
    assert response.status_code == 409 and response.json()["error"]["code"] == "provider_invalid"


def test_plain_http_is_allowed_only_where_the_settings_allow_it(world, settings):
    settings.SSO_ALLOW_HTTP_ISSUERS = True  # local Keycloak in development and tests
    admin = login("admin@example.com")
    response = admin.post(
        "/api/sso/providers/", {**PROVIDER, "issuer": "http://localhost:8180/realms/vtc"}, format="json"
    )
    assert response.status_code == 201


def test_the_connection_test_checks_discovery_and_keys(world, monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": PROVIDER["issuer"],
                "authorization_endpoint": PROVIDER["issuer"] + "/auth",
                "token_endpoint": PROVIDER["issuer"] + "/token",
                "jwks_uri": PROVIDER["issuer"] + "/certs",
            }
        return {"keys": [{"kty": "RSA", "kid": "k", "n": "AQAB", "e": "AQAB"}]}

    monkeypatch.setattr(services, "fetch_json", fetch)
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)
        tested = services.test_connection(config, actor=world["admin"])
    assert tested.discovery_ok_at is not None and tested.last_test_error == ""
    assert calls == [PROVIDER["issuer"] + "/.well-known/openid-configuration", PROVIDER["issuer"] + "/certs"]


def test_a_discovery_document_for_another_issuer_fails_the_test(world, monkeypatch):
    monkeypatch.setattr(
        services,
        "fetch_json",
        lambda url: {
            "issuer": "https://evil.test",
            "authorization_endpoint": "x",
            "token_endpoint": "y",
            "jwks_uri": "z",
        },
    )
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)
        with pytest.raises(Conflict) as failed:
            services.test_connection(config, actor=world["admin"])
        assert failed.value.get_codes() == "provider_test_failed"
        config.refresh_from_db()
        assert config.discovery_ok_at is None and "issuer" in config.last_test_error


def test_changing_the_provider_clears_its_tests(world, monkeypatch):
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)
        IdentityProviderConfig.objects.filter(pk=config.pk).update(
            discovery_ok_at=config.config_changed_at, test_login_ok_at=config.config_changed_at
        )
        changed = services.save_provider(config, actor=world["admin"], **{**PROVIDER, "client_id": "other"})
    assert changed.discovery_ok_at is None and changed.test_login_ok_at is None


def test_one_provider_per_organization_and_unverified_domains_may_be_listed(world, txt):
    admin = login("admin@example.com")
    assert admin.post("/api/sso/providers/", PROVIDER, format="json").status_code == 201
    again = admin.post("/api/sso/providers/", PROVIDER, format="json")
    assert again.json()["error"]["code"] == "provider_exists"
    domain = admin.post("/api/sso/domains/", {"domain": "vtc.test"}, format="json").json()
    assert domain["verified_at"] is None and domain["record_name"] == "_harak2-verification.vtc.test"
    assert [d["domain"] for d in admin.get("/api/sso/domains/").json()] == ["vtc.test"]
