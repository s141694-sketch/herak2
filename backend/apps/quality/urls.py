from django.urls import path

from . import views

urlpatterns = [
    path("program-versions/<int:pk>/quality/", views.VersionQualityView.as_view(), name="version-quality"),
    path("program-versions/<int:pk>/quality/run/", views.VersionQualityRunView.as_view(), name="version-quality-run"),
    path("findings/<int:pk>/dismiss/", views.DismissFindingView.as_view(), name="finding-dismiss"),
    path("findings/<int:pk>/restore/", views.RestoreFindingView.as_view(), name="finding-restore"),
]
