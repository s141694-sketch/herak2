from django.urls import path

from . import views

urlpatterns = [
    path("files/<int:pk>/download/", views.FileDownloadView.as_view(), name="file-download"),
]
