from django.urls import path

from . import views

urlpatterns = [path("ai/policy/", views.AIPolicyView.as_view(), name="ai-policy")]
