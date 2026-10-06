from django.urls import path

from . import views

urlpatterns = [
    path("sso/domains/", views.DomainListView.as_view(), name="sso-domain-list"),
    path("sso/domains/<int:pk>/", views.DomainDetailView.as_view(), name="sso-domain-detail"),
    path("sso/domains/<int:pk>/verify/", views.DomainVerifyView.as_view(), name="sso-domain-verify"),
    path("sso/providers/", views.ProviderListView.as_view(), name="sso-provider-list"),
    path("sso/providers/<int:pk>/", views.ProviderDetailView.as_view(), name="sso-provider-detail"),
    path("sso/providers/<int:pk>/test/", views.ProviderTestView.as_view(), name="sso-provider-test"),
    path("sso/providers/<int:pk>/test-login/", views.ProviderTestLoginView.as_view(), name="sso-provider-test-login"),
    path("sso/providers/<int:pk>/policy/", views.ProviderPolicyView.as_view(), name="sso-provider-policy"),
    path("auth/sso/discover/", views.SsoDiscoverView.as_view(), name="auth-sso-discover"),
    path("auth/sso/start/", views.SsoStartView.as_view(), name="auth-sso-start"),
    path("auth/sso/callback/", views.SsoCallbackView.as_view(), name="auth-sso-callback"),
]
