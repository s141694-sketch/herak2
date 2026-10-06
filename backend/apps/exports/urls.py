from django.urls import path

from . import views

urlpatterns = [
    path("program-versions/<int:pk>/export/", views.VersionExportView.as_view(), name="version-export"),
    path(
        "program-versions/<int:pk>/export/retry/", views.VersionExportRetryView.as_view(), name="version-export-retry"
    ),
]
