"""Setting up an organization's single sign-on (tasks 6.3, 6.4): domains proved by DNS, and its OIDC provider."""

import ipaddress
import json
import re
import secrets as random
import socket
import time
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from apps.audit.services import record
from apps.core.errors import Conflict

from . import dns
from .models import IdentityProviderConfig, VerifiedDomain

LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
HTTP_TIMEOUT = 10
# A discovery document or a key set is a few kilobytes; nothing a provider sends is read past this.
MAX_ANSWER_BYTES = 512 * 1024


class SsoError(Conflict):
    default_code = "sso_error"


# --- Domains (task 6.3) -----------------------------------------------------------------------------------


def normalize_domain(value: str) -> str:
    """A domain as stored: lowercase ASCII (internationalized names in their IDNA form), no trailing dot."""
    domain = (value or "").strip().lower().rstrip(".")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SsoError("this is not a domain name", code="domain_invalid") from exc
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or not all(LABEL.match(label) for label in labels):
        raise SsoError("this is not a domain name", code="domain_invalid")
    return domain


def add_domain(value: str, *, actor) -> VerifiedDomain:
    domain = normalize_domain(value)
    existing = VerifiedDomain.objects.filter(domain=domain).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():  # the same domain added twice at once: the second finds the first
            added = VerifiedDomain.objects.create(domain=domain, token=random.token_urlsafe(32), created_by=actor)
    except IntegrityError:
        return VerifiedDomain.objects.get(domain=domain)
    record("sso.domain_added", actor=actor, target=added, payload={"domain": domain})
    return added


def verify_domain(domain: VerifiedDomain, *, actor) -> VerifiedDomain:
    """Checks the TXT record now. A domain another organization verified first stays theirs."""
    now = timezone.now()
    # Why it failed is kept as a code the interface translates, with the technical detail beside it.
    try:
        found = dns.txt_records(domain.record_name)
    except dns.LookupFailed as exc:
        code, error = "domain_record_missing", f"{domain.record_name}: {exc}"
    else:
        code, error = ("", "") if domain.record_value in found else ("domain_record_mismatch", domain.record_name)
    if code:
        VerifiedDomain.objects.filter(pk=domain.pk).update(
            last_checked_at=now, last_error=error[:500], last_error_code=code
        )
        raise SsoError(error, code=code)
    try:
        with transaction.atomic():
            VerifiedDomain.objects.filter(pk=domain.pk).update(
                verified_at=now, last_checked_at=now, last_error="", last_error_code=""
            )
    except IntegrityError as exc:
        raise SsoError("another organization has verified this domain", code="domain_taken") from exc
    record("sso.domain_verified", actor=actor, target=domain, payload={"domain": domain.domain})
    domain.refresh_from_db()
    return domain


@transaction.atomic
def remove_domain(domain: VerifiedDomain, *, actor) -> None:
    """A verified domain goes, except the last one while single sign-on is enforced: its members would have no way in
    (passwords refused, and no domain to sign in through)."""
    enforced = IdentityProviderConfig.objects.select_for_update().filter(enforced=True).exists()
    others = VerifiedDomain.objects.filter(verified_at__isnull=False).exclude(pk=domain.pk)
    if domain.verified_at is not None and enforced and not others.exists():
        raise SsoError("stop enforcing single sign-on first", code="domain_needed_by_enforcement")
    record("sso.domain_removed", actor=actor, target=domain, payload={"domain": domain.domain})
    domain.delete()


# --- The identity provider (task 6.4) ---------------------------------------------------------------------


class ProviderAnswerError(ValueError):
    """The provider answered, or would be reached, in a way that cannot be used; ``code`` says which, for the
    interface to translate."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def _web_url(url) -> bool:
    """An absolute https URL (http only for a local test provider): what the browser and this server may be sent to."""
    if not isinstance(url, str) or len(url) > 2000:
        return False
    parsed = urlparse(url)
    allowed = {"https", "http"} if settings.SSO_ALLOW_HTTP_ISSUERS else {"https"}
    return parsed.scheme in allowed and bool(parsed.hostname) and parsed.username is None and parsed.password is None


def _clean_issuer(issuer: str) -> str:
    """The issuer exactly as the provider names itself (a trailing slash included, as Auth0's has): its tokens are
    compared with it character for character (OpenID Connect Discovery 1.0, 4.3)."""
    issuer = (issuer or "").strip()
    parsed = urlparse(issuer)
    if not _web_url(issuer) or parsed.query or parsed.fragment or len(issuer) > 500:
        raise SsoError("the issuer is an https URL", code="provider_invalid")
    return issuer


@transaction.atomic
def save_provider(
    config: IdentityProviderConfig | None, *, actor, issuer: str, client_id: str, client_secret: str = ""
):
    """Creates or changes the provider. A blank secret keeps the stored one. Any change clears the tests: the
    provider must be tested again before enforcement (spec 7.2)."""
    issuer = _clean_issuer(issuer)
    client_id = (client_id or "").strip()
    if not client_id or len(client_id) > 255:
        raise SsoError("the client id is required", code="provider_invalid")
    if config is None:
        if IdentityProviderConfig.objects.exists():
            raise SsoError("the organization has a provider already", code="provider_exists")
        if not client_secret:
            raise SsoError("the client secret is required", code="provider_invalid")
        config = IdentityProviderConfig(issuer=issuer, client_id=client_id)
        changed = True
    else:
        config = IdentityProviderConfig.objects.select_for_update().get(pk=config.pk)
        moved = (issuer, client_id) != (config.issuer, config.client_id)
        if moved and not client_secret:
            # The stored secret was given for that provider and client: it is never sent anywhere else.
            raise SsoError("give the client secret for this provider", code="provider_secret_required")
        changed = moved or bool(client_secret)
        config.issuer, config.client_id = issuer, client_id
    if client_secret:
        config.client_secret = client_secret
    if changed:
        config.config_changed_at = timezone.now()
        config.discovery_ok_at = config.test_login_ok_at = None
        # A changed provider is not used at all until its connection is tested again (spec 7.7), nor trusted to
        # be the only way in until a test sign-in passes again (spec 7.2).
        config.enabled = config.enforced = False
    try:
        with transaction.atomic():
            config.save()
    except IntegrityError as exc:  # two first providers saved at once
        raise SsoError("the organization has a provider already", code="provider_exists") from exc
    record("sso.provider_saved", actor=actor, target=config, payload={"issuer": issuer, "client_id": client_id})
    return config


def _public_address(host: str, port: int) -> None:
    """Refuses a host that is, or resolves to, an address that is not public: a provider's settings must not make
    this server reach its own network (loopback, private ranges, link-local and cloud metadata, shared space).
    Development and tests allow a local Keycloak (D62)."""
    if settings.SSO_ALLOW_PRIVATE_ADDRESSES:
        return
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise requests.ConnectionError(f"{host} cannot be resolved") from exc
    for answer in answers:
        address = ipaddress.ip_address(answer[4][0].split("%")[0])
        if not address.is_global:
            raise ProviderAnswerError("provider_address_not_allowed", f"{host} is not a public address")


class _PublicPeer:
    """A connection that closes at once if it reached an address that is not public. The name was checked when it
    was resolved (check_url), but it may resolve elsewhere by the time of the connection ("DNS rebinding"); the
    address the socket actually reached is what counts (task 8.4, the limit phase 6 left)."""

    def _new_conn(self):
        sock = super()._new_conn()
        # Through an outbound proxy the socket's peer is the proxy, which the operator set, and the proxy resolves
        # the name: the check at resolution (check_url) is then what stands.
        if not settings.SSO_ALLOW_PRIVATE_ADDRESSES and self.proxy is None:
            peer = ipaddress.ip_address(sock.getpeername()[0].split("%")[0])
            if not peer.is_global:
                sock.close()
                raise OSError(f"{self.host} led to {peer}, which is not a public address")
        return sock


class _PublicHTTPConnection(_PublicPeer, HTTPConnection):
    pass


class _PublicHTTPSConnection(_PublicPeer, HTTPSConnection):
    pass


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicOnly(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PublicHTTPPool, "https": _PublicHTTPSPool}


def public_session(session: requests.Session | None = None) -> requests.Session:
    """A requests session (or the one given, such as Authlib's) whose connections reach public addresses only."""
    session = session or requests.Session()
    session.mount("http://", _PublicOnly())
    session.mount("https://", _PublicOnly())
    return session


def check_url(url) -> None:
    """What this server may send a request to on a provider's behalf."""
    if not _web_url(url):
        raise ProviderAnswerError("provider_endpoint_invalid", f"{url!r} is not an https URL")
    parsed = urlparse(url)
    _public_address(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


def fetch_json(url: str) -> dict:
    """A JSON object from the provider: no redirect followed (it could lead inside), at most MAX_ANSWER_BYTES, and
    within HTTP_TIMEOUT overall."""
    check_url(url)
    response = public_session().get(
        url, timeout=HTTP_TIMEOUT, headers={"Accept": "application/json"}, allow_redirects=False, stream=True
    )
    try:
        if response.is_redirect or 300 <= response.status_code < 400:
            raise ProviderAnswerError("provider_answer_invalid", f"{url} answered with a redirect")
        response.raise_for_status()
        deadline, body = time.monotonic() + HTTP_TIMEOUT, bytearray()
        for chunk in response.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_ANSWER_BYTES:
                raise ProviderAnswerError("provider_answer_invalid", f"the answer of {url} is too large")
            if time.monotonic() > deadline:
                raise requests.Timeout(f"{url} answered too slowly")
    finally:
        response.close()
    try:
        data = json.loads(bytes(body))
    except ValueError as exc:
        raise ProviderAnswerError("provider_answer_invalid", f"the answer of {url} is not JSON") from exc
    if not isinstance(data, dict):
        raise ProviderAnswerError("provider_answer_invalid", f"the answer of {url} is not a JSON object")
    return data


def discovery(issuer: str) -> dict:
    """The provider's OIDC discovery document, checked to be its own (OpenID Connect Discovery 1.0, 4.3)."""
    meta = fetch_json(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
    if meta.get("issuer") != issuer:
        raise ProviderAnswerError(
            "provider_issuer_mismatch",
            f"the discovery document names the issuer {meta.get('issuer')!r}, not {issuer!r}",
        )
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        # The browser is sent to the first one: a javascript: or relative URL there would run in Harak's origin.
        if not _web_url(meta.get(key)):
            raise ProviderAnswerError("provider_endpoint_invalid", f"the discovery document has no https {key}")
    return meta


def test_connection(config: IdentityProviderConfig, *, actor) -> IdentityProviderConfig:
    """Reaches the provider: its discovery document, and its signing keys. The result counts only for the
    configuration it tested: one changed meanwhile is tested again."""
    current = IdentityProviderConfig.objects.filter(pk=config.pk, config_changed_at=config.config_changed_at)
    try:
        meta = discovery(config.issuer)
        keys = fetch_json(meta["jwks_uri"]).get("keys")
        if not isinstance(keys, list) or not keys:
            raise ProviderAnswerError("provider_no_keys", "the provider publishes no signing keys")
    except (requests.RequestException, ValueError) as exc:
        code = exc.code if isinstance(exc, ProviderAnswerError) else "provider_unreachable"
        current.update(discovery_ok_at=None, last_test_error=str(exc)[:2000], last_test_error_code=code)
        record("sso.provider_test_failed", actor=actor, target=config, payload={"error": str(exc)[:500], "code": code})
        raise SsoError(f"the provider could not be reached correctly: {exc}", code="provider_test_failed") from exc
    if not current.update(discovery_ok_at=timezone.now(), last_test_error="", last_test_error_code=""):
        raise SsoError("the provider was changed meanwhile: test it again", code="provider_changed")
    record("sso.provider_tested", actor=actor, target=config)
    config.refresh_from_db()
    return config


@transaction.atomic
def set_policy(config: IdentityProviderConfig, *, actor, enabled: bool, enforced: bool = False, emergency_user=None):
    """Who may and who must sign in through the provider. Members sign in through it once its connection test
    passed; it becomes the only way in (enforcement) once a test sign-in passed too, and with an emergency
    admin account that keeps its password (spec 7.2, D66)."""
    from apps.accounts.members import _lock_organization
    from apps.accounts.mfa import confirmed_device
    from apps.accounts.models import Membership, Role

    # Waits for a role change in progress, which might be demoting the account named here (phase 8 review).
    _lock_organization()
    config = IdentityProviderConfig.objects.select_for_update().get(pk=config.pk)
    if (enabled or enforced) and config.discovery_ok_at is None:
        raise SsoError("test the connection first", code="provider_not_tested")
    if enforced:
        if not enabled:
            raise SsoError("enforcement needs single sign-on enabled", code="provider_invalid")
        if not config.tested:
            raise SsoError("sign in once through the provider as a test first", code="provider_not_tested")
        if emergency_user is None:
            raise SsoError("name the emergency account first", code="emergency_account_required")
        if not VerifiedDomain.objects.filter(verified_at__isnull=False).exists():
            # Members sign in through the provider by their email's verified domain: without one nobody could.
            raise SsoError("verify a domain first", code="domain_required")
    if emergency_user is not None and not Membership.objects.filter(user=emergency_user, role=Role.ADMIN).exists():
        raise SsoError("the emergency account is one of the organization's admins", code="emergency_account_invalid")
    if enforced and confirmed_device(emergency_user) is None:
        # Spec 7.2: the one account that keeps its password has a second factor, always.
        raise SsoError("the emergency account must use two-factor authentication", code="emergency_account_needs_mfa")
    config.enabled, config.enforced, config.emergency_user = enabled, enforced, emergency_user
    config.save(update_fields=["enabled", "enforced", "emergency_user", "updated_at"])
    record(
        "sso.policy_set",
        actor=actor,
        target=config,
        payload={"enabled": enabled, "enforced": enforced, "emergency_user": getattr(emergency_user, "pk", None)},
    )
    return config
