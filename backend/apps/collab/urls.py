from django.urls import path

from . import views

urlpatterns = [
    path(
        "program-versions/<int:pk>/collab-token/", views.CollabTokenView.as_view(), name="program-version-collab-token"
    ),
]
