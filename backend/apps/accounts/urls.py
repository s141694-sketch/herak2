from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("auth/mfa/verify/", views.MfaVerifyView.as_view(), name="auth-mfa-verify"),
    path("auth/mfa/enrol/", views.MfaEnrolView.as_view(), name="auth-mfa-enrol"),
    path("auth/mfa/confirm/", views.MfaConfirmView.as_view(), name="auth-mfa-confirm"),
    path("auth/mfa/disable/", views.MfaDisableView.as_view(), name="auth-mfa-disable"),
    path("auth/switch-organization/", views.SwitchOrganizationView.as_view(), name="auth-switch-organization"),
    path(
        "auth/invitations/<int:pk>/<str:answer>/",
        views.InvitationAnswerView.as_view(),
        name="auth-invitation-answer",
    ),
    path("auth/password/forgot/", views.ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("auth/password/set/", views.SetPasswordView.as_view(), name="auth-password-set"),
    path("organizations/current/", views.CurrentOrganizationView.as_view(), name="organization-current"),
    path("organizations/current/identity/", views.IdentityView.as_view(), name="organization-identity"),
    path("organizations/current/identity/logo/", views.IdentityLogoView.as_view(), name="organization-identity-logo"),
    path("organizations/current/members/", views.MemberListView.as_view(), name="member-list"),
    path("organizations/current/members/<int:pk>/", views.MemberDetailView.as_view(), name="member-detail"),
    path(
        "organizations/current/members/<int:pk>/reset-mfa/", views.MemberMfaResetView.as_view(), name="member-reset-mfa"
    ),
]
