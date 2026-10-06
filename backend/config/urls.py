from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def _admin_login(request, extra_context=None):
    """The admin site is entered through Harak's own sign-in, which asks for the second factor and applies single
    sign-on enforcement (spec 7.1, 7.2); Django's admin login would skip both. A signed-in staff member then opens
    /admin/ as usual."""
    return redirect(f"{settings.APP_URL.rstrip('/')}/login")


admin.site.login = _admin_login

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.competencies.urls")),
    path("api/", include("apps.structures.urls")),
    path("api/", include("apps.programs.urls")),
    path("api/", include("apps.collab.urls")),
    path("api/", include("apps.comments.urls")),
    path("api/", include("apps.quality.urls")),
    path("api/", include("apps.ai.urls")),
    path("api/", include("apps.suggestions.urls")),
    path("api/", include("apps.workflows.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.sso.urls")),
    path("api/", include("apps.files.urls")),
    path("api/", include("apps.exports.urls")),
]
