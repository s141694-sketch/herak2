from django.urls import path

from . import views

urlpatterns = [
    path("structure-templates/", views.TemplateListView.as_view(), name="structure-template-list"),
    path("structure-templates/<int:pk>/", views.TemplateDetailView.as_view(), name="structure-template-detail"),
    path(
        "structure-templates/<int:pk>/versions/",
        views.TemplateVersionsView.as_view(),
        name="structure-template-versions",
    ),
    path("template-versions/<int:pk>/", views.TemplateVersionDetailView.as_view(), name="template-version-detail"),
    path(
        "template-versions/<int:pk>/levels/", views.TemplateVersionLevelsView.as_view(), name="template-version-levels"
    ),
    path(
        "template-versions/<int:pk>/publish/",
        views.PublishTemplateVersionView.as_view(),
        name="template-version-publish",
    ),
]
