from django.urls import path

from . import views

urlpatterns = [
    path("sso/domains/", views.DomainListView.as_view(), name="sso-domain-list"),
    path("sso/domains/<int:pk>/", views.DomainDetailView.as_view(), name="sso-domain-detail"),
    path("sso/domains/<int:pk>/verify/", views.DomainVerifyView.as_view(), name="sso-domain-verify"),
    path("sso/providers/", views.ProviderListView.as_view(), name="sso-provider-list"),
    path("sso/providers/<int:pk>/", views.ProviderDetailView.as_view(), name="sso-provider-detail"),
    path("sso/providers/<int:pk>/test/", views.ProviderTestView.as_view(), name="sso-provider-test"),
]
