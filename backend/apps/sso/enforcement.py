"""Enforcing single sign-on (D66): a session enters an enforcing organization only if it signed in through that
organization's provider, or it is the emergency account's password session with its second factor checked.

A session opened by single sign-on alone works only in the organizations whose provider signed it in (D71): one
organization's provider does not vouch for the person in their other organizations, which never chose to trust it.
"""

from apps.tenancy.middleware import SESSION_MFA, SESSION_SSO_ONLY, sso_organizations

from .models import IdentityProviderConfig


def sso_entry_check(request, membership) -> str | None:
    config = (
        IdentityProviderConfig.all_organizations.filter(organization_id=membership.organization_id, enforced=True)
        .only("emergency_user_id")
        .first()
    )
    if config is None:
        return None
    session = request.session
    if membership.organization_id in sso_organizations(session):
        return None
    if config.emergency_user_id == membership.user_id and session.get(SESSION_MFA):
        return None
    return "sso_required"


def sso_scope_entry_check(request, membership) -> str | None:
    session = request.session
    if session.get(SESSION_SSO_ONLY) and membership.organization_id not in sso_organizations(session):
        return "password_required"
    return None
