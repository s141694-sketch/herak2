"""Request-level checks: an active organization first, then the member's role in it."""

from rest_framework import exceptions, permissions

from apps.accounts.models import Role


class NoActiveOrganization(exceptions.APIException):
    status_code = 409
    default_detail = "choose an organization first"
    default_code = "no_active_organization"


class HasActiveOrganization(permissions.BasePermission):
    """The session names an organization the user belongs to, with a role other than pending."""

    def has_permission(self, request, view):
        if getattr(request, "organization", None) is None:
            raise NoActiveOrganization()
        membership = getattr(request, "membership", None)
        return membership is not None and membership.role != Role.PENDING


def role_required(*roles: str):
    class RoleRequired(HasActiveOrganization):
        def has_permission(self, request, view):
            return super().has_permission(request, view) and request.membership.role in roles

    RoleRequired.__name__ = f"RoleRequired[{','.join(roles)}]"
    return RoleRequired


class AdminWritesMembersRead(HasActiveOrganization):
    """Any active member may read; only the organization's admin may write."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.method in permissions.SAFE_METHODS or request.membership.role == Role.ADMIN
