"""Enforcing single sign-on (D66): a session enters an enforcing organization only if it signed in through that
organization's provider, or it is the emergency account's password session with its second factor checked."""

from .models import IdentityProviderConfig

# Set in the session once the second factor was checked (task 6.7).
SESSION_MFA = "mfa_verified"


def sso_entry_check(request, membership) -> str | None:
    from .login import SESSION_SSO

    config = (
        IdentityProviderConfig.all_organizations.filter(organization_id=membership.organization_id, enforced=True)
        .only("emergency_user_id")
        .first()
    )
    if config is None:
        return None
    session = request.session
    if membership.organization_id in session.get(SESSION_SSO, []):
        return None
    if config.emergency_user_id == membership.user_id and session.get(SESSION_MFA):
        return None
    return "sso_required"
