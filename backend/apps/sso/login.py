"""Signing in through the organization's OIDC provider (tasks 6.5, 6.6; spec 7.2).

The email's domain leads to the organization that verified it and to its provider. The browser goes there with
an authorization request (state, nonce, PKCE S256) and comes back with a code; the code is exchanged for an ID
token, which is checked against the provider's keys, issuer, audience, expiry and nonce. The person is the one
the provider knew by that subject, or the account of a verified email in one of the organization's verified
domains (D65); a newcomer joins the organization pending an assignment. The session works in that organization
for the length the organization set (D68).

An admin's test sign-in runs the same flow without signing anyone in, and records that the provider works.
"""

import time
from urllib.parse import urlencode

import requests
import structlog
from authlib.common.security import generate_token
from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.utils import timezone
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from rest_framework.exceptions import APIException

from apps.accounts.models import Membership, Organization, Role, User
from apps.audit.services import record
from apps.core.errors import Conflict
from apps.tenancy.context import organization_context
from apps.tenancy.middleware import SESSION_KEY, SESSION_SSO

from . import services
from .models import ExternalIdentity, IdentityProviderConfig, VerifiedDomain

log = structlog.get_logger("harak2.sso")
SESSION_FLOW = "sso_flow"
FLOW_SECONDS = 10 * 60
LEEWAY_SECONDS = 60


class SsoNotAvailable(Conflict):
    default_code = "sso_not_available"
    default_detail = "this email has no single sign-on"


class ProviderUnavailable(APIException):
    status_code = 503
    default_code = "provider_unavailable"
    default_detail = "the organization's identity provider cannot be reached"


class Refused(Exception):
    """The sign-in ends here; ``code`` is what the sign-in page says."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def callback_url() -> str:
    return settings.SSO_CALLBACK_URL or f"{settings.APP_URL.rstrip('/')}/api/auth/sso/callback/"


def domain_of(email: str) -> str:
    _, at, domain = (email or "").strip().lower().rpartition("@")
    return domain if at and domain else ""


def provider_for_email(email: str) -> IdentityProviderConfig | None:
    """The enabled provider of the organization that verified this email's domain, if any."""
    domain = domain_of(email)
    if not domain:
        return None
    verified = VerifiedDomain.all_organizations.filter(domain=domain, verified_at__isnull=False).first()
    if verified is None:
        return None
    return IdentityProviderConfig.all_organizations.filter(
        organization_id=verified.organization_id, enabled=True
    ).first()


def _discovery(config: IdentityProviderConfig) -> dict:
    try:
        return services.discovery(config.issuer)
    except (requests.RequestException, ValueError) as exc:
        log.warning("sso.provider_unavailable", provider=config.pk, error=str(exc))
        raise ProviderUnavailable() from exc


def begin(request, config: IdentityProviderConfig, *, email: str = "", test_by=None) -> str:
    """The authorization URL; what the callback must find is kept in this browser's session."""
    meta = _discovery(config)
    state, nonce, verifier = generate_token(32), generate_token(32), generate_token(64)
    request.session[SESSION_FLOW] = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "provider": config.pk,
        "started": time.time(),
        "changed": config.config_changed_at.isoformat(),
        "test_by": test_by.pk if test_by is not None else None,
    }
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": callback_url(),
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": create_s256_code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    if email:
        params["login_hint"] = email.strip().lower()
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(meta: dict, config: IdentityProviderConfig, code: str, verifier: str, redirect_uri: str) -> dict:
    client = OAuth2Session(config.client_id, config.client_secret, redirect_uri=redirect_uri)
    return client.fetch_token(
        meta["token_endpoint"], grant_type="authorization_code", code=code, code_verifier=verifier, timeout=10
    )


def validate_id_token(token: str, meta: dict, config: IdentityProviderConfig, nonce: str) -> dict:
    try:
        keys = KeySet.import_key_set(services.fetch_json(meta["jwks_uri"]))
        decoded = jwt.decode(token, keys)
        jwt.JWTClaimsRegistry(
            leeway=LEEWAY_SECONDS,
            iss={"essential": True, "value": config.issuer},
            aud={"essential": True, "value": config.client_id},
            sub={"essential": True},
            exp={"essential": True},
            nonce={"essential": True, "value": nonce},
        ).validate(decoded.claims)
    except (JoseError, ValueError, KeyError, TypeError) as exc:
        raise Refused("sso_token_invalid", str(exc)) from exc
    return decoded.claims


def _identify(config: IdentityProviderConfig, claims: dict) -> User:
    """The person behind the claims (D65), created if new; a member of the organization, pending if new to it."""
    identity = (
        ExternalIdentity.objects.filter(issuer=config.issuer, subject=claims["sub"]).select_related("user").first()
    )
    if identity is not None:
        user = identity.user
    else:
        email = str(claims.get("email") or "").strip().lower()
        if claims.get("email_verified") is not True:
            raise Refused("sso_email_unverified")
        if not VerifiedDomain.objects.filter(domain=domain_of(email), verified_at__isnull=False).exists():
            raise Refused("sso_domain_not_allowed")
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email=email, password=None, full_name=str(claims.get("name") or "")[:200])
        identity = ExternalIdentity.objects.create(user=user, issuer=config.issuer, subject=claims["sub"])
    ExternalIdentity.objects.filter(pk=identity.pk).update(last_login_at=timezone.now())
    Membership.objects.get_or_create(user=user, defaults={"role": Role.PENDING})
    return user


def complete(request) -> str:
    """Handles the provider's answer and returns where the browser goes next."""
    flow = request.session.pop(SESSION_FLOW, None)
    base = settings.APP_URL.rstrip("/")
    if not flow or request.GET.get("state") != flow["state"] or time.time() - flow["started"] > FLOW_SECONDS:
        return f"{base}/login?sso_error=sso_state_invalid"
    config = IdentityProviderConfig.all_organizations.filter(pk=flow["provider"]).first()
    testing = flow["test_by"] is not None
    if config is None or (testing and (not request.user.is_authenticated or request.user.pk != flow["test_by"])):
        return f"{base}/login?sso_error=sso_state_invalid"
    done = f"{base}/settings/security?sso_test=" if testing else f"{base}/login?sso_error="
    try:
        if request.GET.get("error"):
            raise Refused("sso_denied", request.GET.get("error", ""))
        with organization_context(config.organization_id):
            meta = _discovery(config)
            try:
                tokens = exchange_code(meta, config, request.GET.get("code", ""), flow["verifier"], callback_url())
            except Exception as exc:  # the provider refused the code, or could not be reached
                raise Refused("sso_token_invalid", str(exc)) from exc
            claims = validate_id_token(tokens.get("id_token", ""), meta, config, flow["nonce"])
            if testing:
                return _record_test(config, flow, actor=request.user, done=done)
            with transaction.atomic():
                user = _identify(config, claims)
                record("sso.login", actor=user, target=config, payload={"subject": claims["sub"]})
    except Refused as refused:
        log.info("sso.refused", provider=config.pk, code=refused.code, detail=str(refused))
        return f"{done}{refused.code}"
    except ProviderUnavailable:
        return f"{done}provider_unavailable"

    organization = Organization.objects.get(pk=config.organization_id)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[SESSION_KEY] = organization.pk
    request.session[SESSION_SSO] = [organization.pk]
    request.session.set_expiry(organization.sso_session_hours * 3600)
    return f"{base}/"


def _record_test(config: IdentityProviderConfig, flow: dict, *, actor, done: str) -> str:
    """A test sign-in counts only for the configuration it started with (spec 7.2: tested before enforcement)."""
    updated = IdentityProviderConfig.objects.filter(
        pk=config.pk, config_changed_at=timezone.datetime.fromisoformat(flow["changed"])
    ).update(test_login_ok_at=timezone.now())
    if not updated:
        return f"{done}provider_changed"
    record("sso.provider_test_login", actor=actor, target=config)
    return f"{done}ok"
