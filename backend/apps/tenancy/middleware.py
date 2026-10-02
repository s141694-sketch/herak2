"""Activates the organization chosen in the session for the duration of the request."""

from apps.accounts.models import Membership, Organization

from .context import activate, deactivate

SESSION_KEY = "organization_id"


def memberships_of(user):
    """A user's memberships across organizations: the login and switch flows need them without a context."""
    return Membership.all_organizations.filter(user=user).select_related("organization").order_by("organization__name")


class OrganizationContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.organization = self._resolve(request, user)
        if request.organization is not None:
            activate(request.organization)
        try:
            return self.get_response(request)
        finally:
            deactivate()

    @staticmethod
    def _resolve(request, user) -> Organization | None:
        session = request.session
        memberships = list(memberships_of(user))
        wanted = session.get(SESSION_KEY)
        if wanted is not None:
            for membership in memberships:
                if membership.organization_id == wanted:
                    return membership.organization
            del session[SESSION_KEY]
        if len(memberships) == 1:
            session[SESSION_KEY] = memberships[0].organization_id
            return memberships[0].organization
        return None
