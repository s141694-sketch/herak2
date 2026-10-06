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
from datetime import UTC, datetime
from urllib.parse import urlencode

import requests
import structlog
from authlib.common.security import generate_token
from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from django.conf import settings
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.utils import timezone
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from rest_framework.exceptions import APIException

from apps.accounts.models import Membership, Organization, Role, User
from apps.audit.services import record
from apps.core.errors import Conflict
from apps.tenancy.context import organization_context
from apps.tenancy.middleware import SESSION_KEY, SESSION_SSO, SESSION_SSO_ONLY, mark_sso

from . import services
from .models import ExternalIdentity, IdentityProviderConfig, VerifiedDomain

log = structlog.get_logger("harak2.sso")
SESSION_FLOW = "sso_flow"
FLOW_SECONDS = 10 * 60
LEEWAY_SECONDS = 60
# Asymmetric signatures only: a symmetric one (HS*) would be keyed by the client secret, and "none" is no signature.
ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]


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
    """The email's domain in the form domains are stored in (IDNA for internationalized names), or ""."""
    _, at, domain = (email or "").strip().lower().rpartition("@")
    if not (at and domain):
        return ""
    try:
        return services.normalize_domain(domain)
    except services.SsoError:
        return ""


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


LANGUAGES = ("ar", "en")


def begin(request, config: IdentityProviderConfig, *, email: str = "", test_by=None, language=None) -> str:
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
    if language in LANGUAGES:
        params["ui_locales"] = language  # the provider's page in the interface's language, where it has it
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(meta: dict, config: IdentityProviderConfig, code: str, verifier: str, redirect_uri: str) -> dict:
    services.check_url(meta["token_endpoint"])  # the client secret goes there: only to a public https address
    client = OAuth2Session(config.client_id, config.client_secret, redirect_uri=redirect_uri)
    return client.fetch_token(
        meta["token_endpoint"],
        grant_type="authorization_code",
        code=code,
        code_verifier=verifier,
        timeout=services.HTTP_TIMEOUT,
        allow_redirects=False,
    )


def validate_id_token(token: str, meta: dict, config: IdentityProviderConfig, nonce: str) -> dict:
    try:
        published = services.fetch_json(meta["jwks_uri"])
    except (requests.RequestException, ValueError) as exc:
        raise ProviderUnavailable() from exc
    try:
        keys = KeySet.import_key_set(published)
        decoded = jwt.decode(token, keys, algorithms=ID_TOKEN_ALGORITHMS)
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


def _known(config: IdentityProviderConfig, claims: dict) -> ExternalIdentity | None:
    return ExternalIdentity.objects.filter(issuer=config.issuer, subject=claims["sub"]).select_related("user").first()


def _linkable_email(claims: dict, *, prefix: str = "sso_") -> str:
    """The email the claims may be linked by (D65): verified by the provider, in a domain this organization
    verified. ``prefix`` names the codes of an admin's test sign-in, which speak of the tested account."""
    email = str(claims.get("email") or "").strip().lower()
    # Microsoft Entra ID sends no email_verified: its optional claim xms_edov says the same (D71).
    verified = claims.get("email_verified") is True or (
        claims.get("email_verified") is None and claims.get("xms_edov") is True
    )
    if not verified:
        raise Refused(f"{prefix}email_unverified")
    if not VerifiedDomain.objects.filter(domain=domain_of(email), verified_at__isnull=False).exists():
        raise Refused(f"{prefix}domain_not_allowed")
    return email


def _admissible(user: User) -> User:
    """Platform staff never sign in through a tenant's provider: it would hand that tenant the platform's admin
    (D71). A deactivated account is told so, before anything is written."""
    if user.is_staff or user.is_superuser:
        raise Refused("sso_account_not_allowed")
    if not user.is_active:
        raise Refused("sso_account_disabled")
    return user


def _identify(config: IdentityProviderConfig, claims: dict) -> User:
    """The person behind the claims (D65), created if new; a member of the organization, pending if new to it."""
    identity = _known(config, claims)
    if identity is not None:
        user = _admissible(identity.user)
    else:
        email = _linkable_email(claims)
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            try:
                with transaction.atomic():  # another first sign-in of the same person may create it meanwhile
                    user = User.objects.create_user(
                        email=email, password=None, full_name=str(claims.get("name") or "")[:200]
                    )
            except IntegrityError:
                user = User.objects.get(email__iexact=email)
        _admissible(user)
        try:
            with transaction.atomic():
                identity = ExternalIdentity.objects.create(user=user, issuer=config.issuer, subject=claims["sub"])
        except IntegrityError:
            identity = _known(config, claims)
            user = _admissible(identity.user)
    ExternalIdentity.objects.filter(pk=identity.pk).update(last_login_at=timezone.now())
    Membership.objects.get_or_create(user=user, defaults={"role": Role.PENDING})
    return user


def complete(request) -> str:
    """Handles the provider's answer and returns where the browser goes next."""
    flow = request.session.pop(SESSION_FLOW, None)
    base = settings.APP_URL.rstrip("/")
    testing = bool(flow) and flow["test_by"] is not None
    # Where the answer is told: an admin's test on the security settings; a browser already signed in on its
    # own page (the sign-in page would only send it on); anyone else on the sign-in page.
    if testing:
        done = f"{base}/settings/security?sso_test="
    elif request.user.is_authenticated:
        done = f"{base}/?sso_error="
    else:
        done = f"{base}/login?sso_error="
    if not flow or request.GET.get("state") != flow["state"] or time.time() - flow["started"] > FLOW_SECONDS:
        return f"{done}sso_state_invalid"
    config = IdentityProviderConfig.all_organizations.filter(pk=flow["provider"]).first()
    if config is None or (testing and (not request.user.is_authenticated or request.user.pk != flow["test_by"])):
        return f"{done}sso_state_invalid"
    if not testing and not config.enabled:
        return f"{done}sso_not_available"  # turned off while the person was at the provider
    try:
        if request.GET.get("error"):
            raise Refused("sso_denied", request.GET.get("error", ""))
        with organization_context(config.organization_id):
            meta = _discovery(config)
            try:
                tokens = exchange_code(meta, config, request.GET.get("code", ""), flow["verifier"], callback_url())
            except (requests.RequestException, services.ProviderAnswerError) as exc:
                log.warning("sso.provider_unavailable", provider=config.pk, error=str(exc))
                raise ProviderUnavailable() from exc
            except Exception as exc:  # the provider refused the code
                raise Refused("sso_token_invalid", str(exc)) from exc
            claims = validate_id_token(tokens.get("id_token", ""), meta, config, flow["nonce"])
            if testing:
                # The test proves members could sign in: the identity must pass the rules theirs will meet.
                if _known(config, claims) is None:
                    _linkable_email(claims, prefix="sso_test_")
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
    already_signed_in = request.user.is_authenticated and request.user.pk == user.pk
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    session = request.session
    # The organization's session length is a deadline from this sign-in, kept with the mark itself: later
    # requests do not move it (D68).
    mark_sso(session, organization.pk, time.time() + organization.sso_session_hours * 3600)
    if not already_signed_in:
        session[SESSION_SSO_ONLY] = True
    if session.get(SESSION_SSO_ONLY):
        last = max(session[SESSION_SSO].values())
        session.set_expiry(datetime.fromtimestamp(last, tz=UTC))  # a fixed moment, not a period of inactivity
    session[SESSION_KEY] = organization.pk
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
