"""Two-factor authentication with TOTP (task 6.7, spec 7.1, D67).

RFC 6238 codes of six digits over 30 seconds, accepted one step either side, never twice. The secret is stored
encrypted (spec 7.4). A password sign-in of someone with a second factor waits in the session for the code;
too many wrong codes send them back to the password. Single sign-on sessions do not use it: the provider does.
"""

import hmac
import time

import pyotp
from django.db import transaction
from django.utils import timezone

from apps.core import secrets
from apps.core.errors import Conflict
from apps.tenancy.middleware import SESSION_MFA, SESSION_SSO

from .models import Role, TOTPDevice, User

ISSUER_NAME = "Harak"
STEP_SECONDS = 30
WINDOW = 1
MAX_ATTEMPTS = 5
PENDING_SECONDS = 5 * 60
SESSION_PENDING = "mfa_pending"
MANAGERS = (Role.ADMIN, Role.APPROVER)


class MfaError(Conflict):
    default_code = "mfa_error"


def confirmed_device(user) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).first()


def begin_enrolment(user) -> tuple[str, str]:
    """A new secret, kept unconfirmed until a code proves the person's app has it."""
    if confirmed_device(user) is not None:
        raise MfaError("two-factor authentication is already on", code="mfa_already_enabled")
    secret = pyotp.random_base32()
    TOTPDevice.objects.update_or_create(
        user=user, defaults={"secret_encrypted": secrets.encrypt(secret), "confirmed_at": None, "last_step": 0}
    )
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER_NAME)
    return secret, uri


def _accept(device: TOTPDevice, code: str) -> bool:
    """Whether the code fits a time step not used yet; that step is then spent."""
    code = (code or "").strip()
    if not (len(code) == 6 and code.isdigit()):
        return False
    totp = pyotp.TOTP(secrets.decrypt(device.secret_encrypted))
    now = int(time.time()) // STEP_SECONDS
    for step in range(now - WINDOW, now + WINDOW + 1):
        if step > device.last_step and hmac.compare_digest(totp.at(step * STEP_SECONDS), code):
            device.last_step = step
            device.save(update_fields=["last_step"])
            return True
    return False


@transaction.atomic
def check_code(user, code: str, *, confirmed: bool = True) -> None:
    query = TOTPDevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=not confirmed)
    device = query.first()
    if device is None:
        raise MfaError("there is no second factor to check", code="mfa_not_enrolled")
    if not _accept(device, code):
        raise MfaError("the code is not right, or was used already", code="mfa_code_invalid")


def confirm_enrolment(request, user, code: str) -> None:
    check_code(user, code, confirmed=False)
    TOTPDevice.objects.filter(user=user).update(confirmed_at=timezone.now())
    request.session[SESSION_MFA] = True


def required_for(user) -> bool:
    """Whether an organization of this person requires a second factor of their role, or they are an emergency
    account (D66): they may not turn it off."""
    from apps.sso.models import IdentityProviderConfig

    from .models import Membership

    managed = Membership.all_organizations.filter(
        user=user, role__in=MANAGERS, organization__mfa_required_for_managers=True
    ).exists()
    emergency = IdentityProviderConfig.all_organizations.filter(emergency_user=user).exists()
    return managed or emergency


def disable(user, code: str) -> None:
    if required_for(user):
        raise MfaError("an organization of yours requires two-factor authentication", code="mfa_required")
    check_code(user, code)
    TOTPDevice.objects.filter(user=user).delete()


# --- The second step of a password sign-in -----------------------------------------------------------------


def hold(request, user) -> None:
    request.session[SESSION_PENDING] = {"user": user.pk, "at": time.time(), "failures": 0}


def pending_user(request) -> User | None:
    pending = request.session.get(SESSION_PENDING)
    if not pending or time.time() - pending["at"] > PENDING_SECONDS:
        request.session.pop(SESSION_PENDING, None)
        return None
    return User.objects.filter(pk=pending["user"], is_active=True).first()


def verify_pending(request, code: str) -> User:
    user = pending_user(request)
    if user is None:
        raise MfaError("sign in with your password again", code="mfa_not_pending")
    try:
        check_code(user, code)
    except MfaError:
        pending = request.session[SESSION_PENDING]
        pending["failures"] += 1
        if pending["failures"] >= MAX_ATTEMPTS:
            request.session.pop(SESSION_PENDING, None)
        else:
            request.session[SESSION_PENDING] = pending
        raise
    request.session.pop(SESSION_PENDING, None)
    return user


# --- Organizations that require it (an entry check, D66/D67) -----------------------------------------------


def mfa_entry_check(request, membership) -> str | None:
    """A manager of an organization that requires a second factor enters it only with that factor checked in
    this session, or through the organization's provider (which then answers for it)."""
    session = request.session
    if not (membership.organization.mfa_required_for_managers and membership.role in MANAGERS):
        return None
    if session.get(SESSION_MFA) or membership.organization_id in session.get(SESSION_SSO, []):
        return None
    return "mfa_required"
