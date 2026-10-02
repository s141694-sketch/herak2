from django.urls import path

from . import views

urlpatterns = [
    path("programs/", views.ProgramListView.as_view(), name="program-list"),
    path("programs/<int:pk>/", views.ProgramDetailView.as_view(), name="program-detail"),
    path("programs/<int:pk>/collaborators/", views.CollaboratorsView.as_view(), name="program-collaborators"),
    path("program-collaborators/<int:pk>/", views.CollaboratorDetailView.as_view(), name="program-collaborator-detail"),
    path("programs/<int:pk>/versions/", views.ProgramVersionsView.as_view(), name="program-versions"),
    path("program-versions/<int:pk>/", views.VersionDetailView.as_view(), name="program-version-detail"),
    path("program-versions/<int:pk>/targets/", views.VersionTargetsView.as_view(), name="program-version-targets"),
    path("program-versions/<int:pk>/submit/", views.SubmitVersionView.as_view(), name="program-version-submit"),
    path("program-versions/<int:pk>/withdraw/", views.WithdrawVersionView.as_view(), name="program-version-withdraw"),
]
