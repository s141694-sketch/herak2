from django.urls import path

from . import internal_views, views

urlpatterns = [
    path(
        "program-versions/<int:pk>/collab-token/", views.CollabTokenView.as_view(), name="program-version-collab-token"
    ),
    path("internal/collab/documents/<int:pk>/", internal_views.DocumentView.as_view(), name="internal-collab-document"),
    path(
        "internal/collab/documents/<int:pk>/failure/",
        internal_views.DocumentFailureView.as_view(),
        name="internal-collab-document-failure",
    ),
]
