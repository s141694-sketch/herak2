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


# --- From the independent review of phase 6 -----------------------------------------------------------------


def _discovered(issuer):
    return {
        "issuer": issuer,
        "authorization_endpoint": issuer.rstrip("/") + "/auth",
        "token_endpoint": issuer.rstrip("/") + "/token",
        "jwks_uri": issuer.rstrip("/") + "/certs",
    }


@pytest.mark.parametrize("change", [{"issuer": "https://evil.test/realms/vtc"}, {"client_id": "another"}])
def test_a_new_issuer_or_client_needs_its_secret_again(world, change):
    """The stored secret was given for one provider: it is never sent to another (it would leak there)."""
    admin = login("admin@example.com")
    created = admin.post("/api/sso/providers/", PROVIDER, format="json").json()
    response = admin.put(
        f"/api/sso/providers/{created['id']}/", {**PROVIDER, **change, "client_secret": ""}, format="json"
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "provider_secret_required"
    with organization_context(world["org"]):
        assert IdentityProviderConfig.objects.get().issuer == PROVIDER["issuer"]


def test_a_changed_provider_is_turned_off_until_it_is_tested_again(world):
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)
        IdentityProviderConfig.objects.filter(pk=config.pk).update(
            enabled=True, discovery_ok_at=config.config_changed_at, test_login_ok_at=config.config_changed_at
        )
        config.refresh_from_db()
        changed = services.save_provider(
            config, actor=world["admin"], **{**PROVIDER, "issuer": "https://typo.vtc.test"}
        )
    assert not changed.enabled and not changed.enforced


def test_an_issuer_ending_with_a_slash_is_kept_exactly_as_the_provider_names_itself(world, monkeypatch):
    issuer = "https://tenant.eu.auth0.com/"
    calls = []

    def fetch(url):
        calls.append(url)
        return (
            _discovered(issuer)
            if url.endswith("openid-configuration")
            else {"keys": [{"kty": "RSA", "n": "AQAB", "e": "AQAB"}]}
        )

    monkeypatch.setattr(services, "fetch_json", fetch)
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **{**PROVIDER, "issuer": issuer})
        assert config.issuer == issuer
        assert services.test_connection(config, actor=world["admin"]).discovery_ok_at is not None
    assert calls[0] == "https://tenant.eu.auth0.com/.well-known/openid-configuration"


@pytest.mark.parametrize("answer", [[], "text", 3])
def test_a_discovery_answer_that_is_not_an_object_fails_the_test_cleanly(world, monkeypatch, answer):
    class Answer:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        is_redirect = False

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            import json

            yield json.dumps(answer).encode()

        def close(self):
            pass

    monkeypatch.setattr(services, "_public_address", lambda host, port: None)
    monkeypatch.setattr(services.requests, "get", lambda *a, **k: Answer())
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)
        with pytest.raises(Conflict) as failed:
            services.test_connection(config, actor=world["admin"])
    assert failed.value.get_codes() == "provider_test_failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/realms/x",
        "https://localhost:6380/",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5:8443/realms/x",
        "https://[::1]/realms/x",
        "https://100.64.0.1/realms/x",
    ],
)
def test_the_server_does_not_fetch_internal_addresses_for_a_provider(settings, monkeypatch, url):
    settings.SSO_ALLOW_PRIVATE_ADDRESSES = False

    def never(*args, **kwargs):
        raise AssertionError("no request should be made")

    monkeypatch.setattr(services.requests, "get", never)
    with pytest.raises(ValueError, match="address"):
        services.fetch_json(url)


def test_a_provider_answer_is_not_followed_elsewhere_nor_read_without_limit(settings, monkeypatch):
    settings.SSO_ALLOW_PRIVATE_ADDRESSES = False
    monkeypatch.setattr(services, "_public_address", lambda host, port: None)

    class Answer:
        def __init__(self, status, chunks):
            self.status_code, self._chunks = status, chunks
            self.is_redirect = status in (301, 302, 303, 307, 308)
            self.headers = {"Location": "http://169.254.169.254/"}

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield from self._chunks

        def close(self):
            pass

    seen = {}

    def get(url, **kwargs):
        seen.update(kwargs)
        return answers.pop(0)

    monkeypatch.setattr(services.requests, "get", get)
    answers = [Answer(302, [])]
    with pytest.raises(ValueError, match="redirect"):
        services.fetch_json("https://idp.example/x")
    assert seen["allow_redirects"] is False
    answers = [Answer(200, [b"{" + b" " * services.MAX_ANSWER_BYTES, b"}"])]
    with pytest.raises(ValueError, match="large"):
        services.fetch_json("https://idp.example/x")


def test_a_connection_test_that_ends_after_the_provider_changed_does_not_count(world, monkeypatch):
    with organization_context(world["org"]):
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)

        def fetch(url):
            if url.endswith("openid-configuration"):
                # Another admin saves a new issuer while this test is still waiting for the old provider.
                current = IdentityProviderConfig.objects.get(pk=config.pk)
                services.save_provider(current, actor=world["admin"], **{**PROVIDER, "issuer": "https://new.vtc.test"})
                return _discovered(PROVIDER["issuer"])
            return {"keys": [{"kty": "RSA", "n": "AQAB", "e": "AQAB"}]}

        monkeypatch.setattr(services, "fetch_json", fetch)
        with pytest.raises(Conflict) as changed:
            services.test_connection(config, actor=world["admin"])
        assert changed.value.get_codes() == "provider_changed"
        assert IdentityProviderConfig.objects.get(pk=config.pk).discovery_ok_at is None


def test_an_email_in_an_internationalized_domain_finds_its_provider(world, txt):
    from apps.sso import login as sso_login

    with organization_context(world["org"]):
        domain = services.add_domain("مثال.عمان", actor=world["admin"])
        txt[domain.record_name] = [domain.record_value]
        services.verify_domain(domain, actor=world["admin"])
        config = services.save_provider(None, actor=world["admin"], **PROVIDER)
        IdentityProviderConfig.objects.filter(pk=config.pk).update(enabled=True)
    assert sso_login.provider_for_email("ali@مثال.عمان") is not None
    assert sso_login.domain_of("ali@مثال.عمان") == domain.domain


def test_adding_the_same_domain_twice_at_once_gives_the_one_domain(world, monkeypatch):
    from apps.sso.models import VerifiedDomain

    real_filter = VerifiedDomain.objects.filter

    def stale(*args, **kwargs):
        if kwargs.get("domain") == "vtc.test" and not real_filter(domain="vtc.test").exists():
            VerifiedDomain.objects.create(domain="vtc.test", token="t", created_by=world["admin"])  # the other request
            return VerifiedDomain.objects.none()
        return real_filter(*args, **kwargs)

    with organization_context(world["org"]):
        monkeypatch.setattr(VerifiedDomain.objects, "filter", stale)
        added = services.add_domain("vtc.test", actor=world["admin"])
        monkeypatch.undo()
        assert VerifiedDomain.objects.filter(domain="vtc.test").count() == 1 and added.domain == "vtc.test"


def test_why_a_domain_or_a_provider_failed_is_kept_as_a_code_the_interface_translates(world, txt, monkeypatch):
    admin = login("admin@example.com")
    domain = admin.post("/api/sso/domains/", {"domain": "vtc.test"}, format="json").json()
    admin.post(f"/api/sso/domains/{domain['id']}/verify/")
    listed = admin.get("/api/sso/domains/").json()[0]
    assert (
        listed["last_error_code"] == "domain_record_missing" and "_harak2-verification.vtc.test" in listed["last_error"]
    )
    txt["_harak2-verification.vtc.test"] = ["something else"]
    admin.post(f"/api/sso/domains/{domain['id']}/verify/")
    assert admin.get("/api/sso/domains/").json()[0]["last_error_code"] == "domain_record_mismatch"
    monkeypatch.setattr(
        services, "fetch_json", lambda url: {**_discovered(PROVIDER["issuer"]), "issuer": "https://evil.test"}
    )
    created = admin.post("/api/sso/providers/", PROVIDER, format="json").json()
    admin.post(f"/api/sso/providers/{created['id']}/test/")
    assert admin.get("/api/sso/providers/").json()[0]["last_test_error_code"] == "provider_issuer_mismatch"
