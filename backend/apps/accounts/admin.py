from django.contrib import admin

from .models import Membership, Organization, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "is_active", "is_staff", "created_at")
    search_fields = ("email", "full_name")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "ai_enabled", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    """Django admin is the platform operator's tool, so it reads across organizations explicitly."""

    list_display = ("user", "organization", "role", "created_at", "accepted_at")
    list_filter = ("role", "organization")

    def get_queryset(self, request):
        # Invitations too (D90): accepted_at is empty until the person accepts.
        return Membership.including_invitations.select_related("user", "organization")

    def has_add_permission(self, request):
        # Writes need an organization context; memberships are created through the API.
        return False

    def has_change_permission(self, request, obj=None):
        return False
