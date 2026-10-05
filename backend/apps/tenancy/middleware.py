"""Activates the organization chosen in the session for the duration of the request."""

from collections.abc import Callable

from apps.accounts.models import Membership
from apps.core.errors import Conflict

from .context import activate, deactivate

SESSION_KEY = "organization_id"

# Conditions on entering an organization's context with this session, registered by the apps that set them
# (single sign-on enforcement, D66). Each returns None to let the session in, or the code of the refusal.
ENTRY_CHECKS: list[Callable[[object, Membership], str | None]] = []


class EntryRefused(Conflict):
    default_code = "entry_refused"
    default_detail = "this session cannot enter that organization"


def entry_refusal(request, membership: Membership) -> str | None:
    """Why this session may not work in the membership's organization, or None."""
    for check in ENTRY_CHECKS:
        refusal = check(request, membership)
        if refusal:
            return refusal
    return None


def memberships_of(user):
    """A user's memberships across organizations: the login and switch flows need them without a context."""
    return Membership.all_organizations.filter(user=user).select_related("organization").order_by("organization__name")


class OrganizationContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = None
        request.membership = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.membership = self._resolve(request, user)
            request.organization = request.membership.organization if request.membership else None
        if request.organization is not None:
            activate(request.organization)
        try:
            return self.get_response(request)
        finally:
            deactivate()

    @staticmethod
    def _resolve(request, user) -> Membership | None:
        session = request.session
        memberships = [m for m in memberships_of(user) if entry_refusal(request, m) is None]
        wanted = session.get(SESSION_KEY)
        if wanted is not None:
            for membership in memberships:
                if membership.organization_id == wanted:
                    return membership
            del session[SESSION_KEY]
        if len(memberships) == 1:
            session[SESSION_KEY] = memberships[0].organization_id
            return memberships[0]
        return None
