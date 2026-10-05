"""Setting up an organization's single sign-on (tasks 6.3, 6.4): domains proved by DNS, and its OIDC provider."""

import re
import secrets as random
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import Conflict

from . import dns
from .models import IdentityProviderConfig, VerifiedDomain

LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
HTTP_TIMEOUT = 10


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
    added = VerifiedDomain.objects.create(domain=domain, token=random.token_urlsafe(32), created_by=actor)
    record("sso.domain_added", actor=actor, target=added, payload={"domain": domain})
    return added


def verify_domain(domain: VerifiedDomain, *, actor) -> VerifiedDomain:
    """Checks the TXT record now. A domain another organization verified first stays theirs."""
    now = timezone.now()
    try:
        found = dns.txt_records(domain.record_name)
    except dns.LookupFailed as exc:
        found, error = [], f"no TXT record found at {domain.record_name} ({exc})"
    else:
        error = "" if domain.record_value in found else f"{domain.record_name} does not hold {domain.record_value}"
    if error:
        VerifiedDomain.objects.filter(pk=domain.pk).update(last_checked_at=now, last_error=error[:500])
        raise SsoError(error, code="domain_record_missing")
    try:
        with transaction.atomic():
            VerifiedDomain.objects.filter(pk=domain.pk).update(verified_at=now, last_checked_at=now, last_error="")
    except IntegrityError as exc:
        raise SsoError("another organization has verified this domain", code="domain_taken") from exc
    record("sso.domain_verified", actor=actor, target=domain, payload={"domain": domain.domain})
    domain.refresh_from_db()
    return domain


def remove_domain(domain: VerifiedDomain, *, actor) -> None:
    record("sso.domain_removed", actor=actor, target=domain, payload={"domain": domain.domain})
    domain.delete()


# --- The identity provider (task 6.4) ---------------------------------------------------------------------


def _clean_issuer(issuer: str) -> str:
    issuer = (issuer or "").strip().rstrip("/")
    parsed = urlparse(issuer)
    allowed = {"https", "http"} if settings.SSO_ALLOW_HTTP_ISSUERS else {"https"}
    if parsed.scheme not in allowed or not parsed.netloc or parsed.query or parsed.fragment or len(issuer) > 500:
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
        changed = (issuer, client_id) != (config.issuer, config.client_id) or bool(client_secret)
        config.issuer, config.client_id = issuer, client_id
    if client_secret:
        config.client_secret = client_secret
    if changed:
        config.config_changed_at = timezone.now()
        config.discovery_ok_at = config.test_login_ok_at = None
        config.enforced = False  # a changed provider is not trusted to be the only way in until tested again
    config.save()
    record("sso.provider_saved", actor=actor, target=config, payload={"issuer": issuer, "client_id": client_id})
    return config


def fetch_json(url: str) -> dict:
    response = requests.get(url, timeout=HTTP_TIMEOUT, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def discovery(issuer: str) -> dict:
    """The provider's OIDC discovery document, checked to be its own (OpenID Connect Discovery 1.0, 4.3)."""
    meta = fetch_json(f"{issuer}/.well-known/openid-configuration")
    if meta.get("issuer") != issuer:
        raise ValueError(f"the discovery document names the issuer {meta.get('issuer')!r}, not {issuer!r}")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not meta.get(key):
            raise ValueError(f"the discovery document has no {key}")
    return meta


def test_connection(config: IdentityProviderConfig, *, actor) -> IdentityProviderConfig:
    """Reaches the provider: its discovery document, and its signing keys."""
    try:
        meta = discovery(config.issuer)
        keys = fetch_json(meta["jwks_uri"]).get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("the provider publishes no signing keys")
    except (requests.RequestException, ValueError) as exc:
        IdentityProviderConfig.objects.filter(pk=config.pk).update(
            discovery_ok_at=None, last_test_error=str(exc)[:2000]
        )
        record("sso.provider_test_failed", actor=actor, target=config, payload={"error": str(exc)[:500]})
        raise SsoError(f"the provider could not be reached correctly: {exc}", code="provider_test_failed") from exc
    IdentityProviderConfig.objects.filter(pk=config.pk).update(discovery_ok_at=timezone.now(), last_test_error="")
    record("sso.provider_tested", actor=actor, target=config)
    config.refresh_from_db()
    return config
