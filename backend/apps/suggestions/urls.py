from django.urls import path

from . import views

urlpatterns = [
    path("program-versions/<int:pk>/suggestions/", views.VersionSuggestionsView.as_view(), name="version-suggestions"),
    path("program-versions/<int:pk>/import-file/", views.ImportFileView.as_view(), name="version-import-file"),
    path("suggestions/<int:pk>/", views.SuggestionDetailView.as_view(), name="suggestion-detail"),
    path("suggestions/<int:pk>/accept/", views.AcceptSuggestionView.as_view(), name="suggestion-accept"),
    path("suggestions/<int:pk>/dismiss/", views.DismissSuggestionView.as_view(), name="suggestion-dismiss"),
]
