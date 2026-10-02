from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("auth/switch-organization/", views.SwitchOrganizationView.as_view(), name="auth-switch-organization"),
    path("organizations/current/", views.CurrentOrganizationView.as_view(), name="organization-current"),
    path("organizations/current/members/", views.MemberListView.as_view(), name="member-list"),
    path("organizations/current/members/<int:pk>/", views.MemberDetailView.as_view(), name="member-detail"),
]
