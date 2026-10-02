from django.urls import path

from . import views

urlpatterns = [
    path("competency-frameworks/", views.FrameworkListView.as_view(), name="competency-framework-list"),
    path("competency-frameworks/<int:pk>/", views.FrameworkDetailView.as_view(), name="competency-framework-detail"),
    path(
        "competency-frameworks/<int:pk>/versions/",
        views.FrameworkVersionsView.as_view(),
        name="competency-framework-versions",
    ),
    path("framework-versions/<int:pk>/", views.FrameworkVersionDetailView.as_view(), name="framework-version-detail"),
    path("framework-versions/<int:pk>/publish/", views.PublishVersionView.as_view(), name="framework-version-publish"),
    path(
        "framework-versions/<int:pk>/competencies/",
        views.VersionCompetenciesView.as_view(),
        name="framework-version-competencies",
    ),
    path("competencies/<int:pk>/", views.CompetencyDetailView.as_view(), name="competency-detail"),
]
