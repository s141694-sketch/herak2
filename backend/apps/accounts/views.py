from django.contrib.auth import authenticate, login, logout
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import exceptions, generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.audit.services import record
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.middleware import (
    SESSION_KEY,
    SESSION_MFA,
    SESSION_SSO_ONLY,
    EntryRefused,
    entry_refusal,
    memberships_of,
    sso_organizations,
)
from apps.tenancy.permissions import HasActiveOrganization, role_required

from . import mfa
from .models import Membership, Role, TOTPDevice
from .serializers import (
    LoginSerializer,
    MemberSerializer,
    OrganizationSerializer,
    SignInRulesSerializer,
    SwitchOrganizationSerializer,
    session_payload,
)


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class InvalidCredentials(exceptions.ValidationError):
    default_code = "invalid_credentials"


def _select_membership(request, membership: Membership | None) -> None:
    request.membership = membership
    request.organization = membership.organization if membership else None
    if membership:
        request.session[SESSION_KEY] = membership.organization_id
    else:
        request.session.pop(SESSION_KEY, None)


class CsrfView(APIView):
    """Sets the CSRF cookie the browser client sends back on every unsafe request."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"detail": "ok"})


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def initial(self, request, *args, **kwargs):
        # DRF only checks CSRF for authenticated sessions; login must be protected too (login CSRF).
        SessionAuthentication().enforce_csrf(request)
        super().initial(request, *args, **kwargs)

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = authenticate(request, username=email, password=serializer.validated_data["password"])
        if user is None:
            raise InvalidCredentials("invalid email or password")
        if mfa.confirmed_device(user) is not None:
            # The password is right; the session waits for the second factor before signing in (D67).
            mfa.hold(request, user)
            return Response({"mfa_required": True})
        return Response(_finish_login(request, user, second_factor=False))


def _finish_login(request, user, *, second_factor: bool) -> dict:
    """Signs the person in and opens the one organization open to this session, if exactly one is.

    ``second_factor`` says whether this sign-in checked the person's code: never what the browser's previous
    session said, which may have been someone else's (D67)."""
    login(request, user)
    session = request.session
    if second_factor:
        session[SESSION_MFA] = True
    else:
        session.pop(SESSION_MFA, None)
    if session.pop(SESSION_SSO_ONLY, None):
        # Signed in through a provider before: the password now opens their other organizations too, and the
        # session lasts as a password session does; the provider's sign-in keeps its own deadline (D68, D71).
        session.set_expiry(None)
    memberships = list(memberships_of(user))
    refusals = [entry_refusal(request, m) for m in memberships]
    open_to_session = [m for m, refusal in zip(memberships, refusals, strict=True) if refusal is None]
    if memberships and not open_to_session and "sso_required" in refusals:
        # Every organization of this person asks for its own provider: a password does not open any (D66).
        logout(request)
        raise EntryRefused("sign in through your organization", code="sso_required")
    _select_membership(request, open_to_session[0] if len(open_to_session) == 1 else None)
    return session_payload(request)


class MfaVerifyView(APIView):
    """The second step of a password sign-in: the code from the person's authenticator app."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def initial(self, request, *args, **kwargs):
        SessionAuthentication().enforce_csrf(request)
        super().initial(request, *args, **kwargs)

    def post(self, request):
        user = mfa.verify_pending(request, _code(request))
        return Response(_finish_login(request, user, second_factor=True))


def _code(request) -> str:
    code = request.data.get("code", "") if isinstance(request.data, dict) else ""
    if not isinstance(code, str):
        raise exceptions.ValidationError({"code": "six digits"})
    return code


class MfaEnrolView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        secret, uri = mfa.begin_enrolment(request.user)
        return Response({"secret": secret, "otpauth_uri": uri})


class MfaConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        mfa.confirm_enrolment(request, request.user, _code(request))
        return Response(session_payload(request))


class MfaDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        mfa.disable(request.user, _code(request))
        request.session.pop(SESSION_MFA, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(session_payload(request))


class SwitchOrganizationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SwitchOrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization_id = serializer.validated_data["organization_id"]
        membership = memberships_of(request.user).filter(organization_id=organization_id).first()
        if membership is None:
            raise exceptions.NotFound("no membership in that organization")
        refusal = entry_refusal(request, membership)
        if refusal:
            raise EntryRefused("this session cannot enter that organization", code=refusal)
        _select_membership(request, membership)
        return Response(session_payload(request))


class CurrentOrganizationView(APIView):
    permission_classes = [HasActiveOrganization]

    def get(self, request):
        return Response(OrganizationSerializer(request.organization).data)

    def patch(self, request):
        if request.membership.role != Role.ADMIN:
            raise exceptions.PermissionDenied("only an admin sets how members sign in")
        serializer = SignInRulesSerializer(request.organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        turning_on = (
            serializer.validated_data.get("mfa_required_for_managers")
            and not request.organization.mfa_required_for_managers
        )
        # Not without a way back in: the admin's own session must meet the rule (a checked second factor, or this
        # organization's provider, which answers for it).
        protected = request.session.get(SESSION_MFA) or request.organization.pk in sso_organizations(request.session)
        if turning_on and not protected:
            raise mfa.MfaError("set up and use your own second factor first", code="mfa_enable_first")
        organization = serializer.save()
        record(
            "organization.sign_in_rules_set", actor=request.user, target=organization, payload=serializer.validated_data
        )
        return Response(OrganizationSerializer(organization).data)


class MemberListView(generics.ListAPIView):
    permission_classes = [HasActiveOrganization]
    serializer_class = MemberSerializer

    def get_queryset(self):
        return Membership.objects.select_related("user").order_by("user__email")


class MemberDetailView(generics.RetrieveAPIView):
    permission_classes = [HasActiveOrganization]
    serializer_class = MemberSerializer

    def get_queryset(self):
        return Membership.objects.select_related("user")


class MemberMfaResetView(APIView):
    """An admin removes the second factor of a member who lost it (D67); they set it up again on next sign-in."""

    permission_classes = [role_required(Role.ADMIN)]

    def post(self, request, pk):
        membership = get_object_or_404(Membership.objects.select_related("user"), pk=pk)
        if membership.user_id == request.user.pk:
            raise mfa.MfaError("turn off your own second factor from your account", code="mfa_reset_self")
        if IdentityProviderConfig.all_organizations.filter(emergency_user=membership.user).exists():
            # Without it the emergency account could not get in when the provider is down (D66): name another
            # emergency account, or stop enforcing, first.
            raise mfa.MfaError("this person is the emergency account", code="mfa_reset_emergency")
        others = Membership.all_organizations.filter(user=membership.user).exclude(organization=request.organization)
        if others.exists():
            # The factor serves their other organizations too: one organization's admin does not remove it.
            raise mfa.MfaError("this person also works in other organizations", code="mfa_reset_other_organizations")
        TOTPDevice.objects.filter(user=membership.user).delete()
        record("mfa.reset", actor=request.user, target=membership, payload={"user": membership.user_id})
        return Response(status=status.HTTP_204_NO_CONTENT)
