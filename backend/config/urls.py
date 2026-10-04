from django.contrib import admin
from django.urls import include, path

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
]
