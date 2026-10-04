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
    path("program-versions/<int:pk>/tree/", views.VersionTreeView.as_view(), name="program-version-tree"),
    path("program-versions/<int:pk>/nodes/", views.VersionNodesView.as_view(), name="program-version-nodes"),
    path("program-versions/<int:pk>/blocks/", views.VersionBlocksView.as_view(), name="program-version-blocks"),
    path("program-nodes/<int:pk>/", views.NodeDetailView.as_view(), name="program-node-detail"),
    path("program-nodes/<int:pk>/move/", views.NodeMoveView.as_view(), name="program-node-move"),
    path("program-nodes/<int:pk>/restore/", views.NodeRestoreView.as_view(), name="program-node-restore"),
    path("program-blocks/<int:pk>/", views.BlockDetailView.as_view(), name="program-block-detail"),
    path("program-blocks/<int:pk>/restore/", views.BlockRestoreView.as_view(), name="program-block-restore"),
    path("program-versions/<int:pk>/alignment-links/", views.VersionLinksView.as_view(), name="program-version-links"),
    path("alignment-links/<int:pk>/", views.LinkDetailView.as_view(), name="alignment-link-detail"),
    path("program-versions/<int:pk>/diff/<int:other>/", views.VersionDiffView.as_view(), name="program-version-diff"),
]
