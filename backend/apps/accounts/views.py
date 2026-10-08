import hashlib

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import exceptions, generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.audit.services import record
from apps.core.errors import Conflict
from apps.files.uploads import UploadThrottle, too_long
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

from . import members, mfa
from .models import Membership, Role, TOTPDevice
from .serializers import (
    ForgotPasswordSerializer,
    IdentitySerializer,
    LoginSerializer,
    MemberRoleSerializer,
    MemberSerializer,
    NewMemberSerializer,
    OrganizationSerializer,
    SetPasswordSerializer,
    SignInRulesSerializer,
    SwitchOrganizationSerializer,
    identity_payload,
    session_payload,
)


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class LoginPaused(exceptions.APIException):
    status_code = 429
    default_code = "login_paused"
    default_detail = "too many wrong passwords for this account: wait, or sign in through your organization"


def login_failures_key(email: str) -> str:
    """Wrong passwords are counted per account too (spec 7.6, D84): guessing one person's password from many
    addresses stops after LOGIN_ACCOUNT_FAILURES within LOGIN_ACCOUNT_PAUSE_MINUTES."""
    return "login-failures:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def login_pause_key(email: str) -> str:
    """Set when an account's wrong passwords reach the limit; its password sign-in waits while it lasts."""
    return "login-paused:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


class IdentityError(Conflict):
    default_code = "identity_error"


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
        failures, paused = login_failures_key(email), login_pause_key(email)
        pause_seconds = settings.LOGIN_ACCOUNT_PAUSE_MINUTES * 60
        # Checked before the password, so a paused account says nothing about whether it was right.
        if cache.get(paused):
            raise LoginPaused()
        user = authenticate(request, username=email, password=serializer.validated_data["password"])
        if user is None:
            cache.add(failures, 0, timeout=pause_seconds)
            if cache.incr(failures) >= settings.LOGIN_ACCOUNT_FAILURES:
                # The pause runs its whole length from the failure that reached the limit, as the message says,
                # not to the end of the window the first failure opened (phase 8 review).
                cache.set(paused, 1, timeout=pause_seconds)
                cache.delete(failures)
            raise InvalidCredentials("invalid email or password")
        cache.delete(failures)
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
    if memberships and all(refusal == "sso_required" for refusal in refusals):
        # Every organization of this person asks for its own provider: a password does not open any (D66). Where
        # another asks for something this session can do (set up a second factor), the person stays signed in.
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
    """The organization's members; an admin adds people by email with a role (spec 2.1, D87)."""

    permission_classes = [HasActiveOrganization]
    serializer_class = MemberSerializer

    def get_queryset(self):
        # Invitations too: the admin follows them and may cancel them (D90).
        return Membership.with_invitations.select_related("user").order_by("user__email")

    def post(self, request):
        if request.membership.role != Role.ADMIN:
            raise exceptions.PermissionDenied("only an admin adds members")
        serializer = NewMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = members.add_member(request.organization, actor=request.user, **serializer.validated_data)
        return Response(MemberSerializer(membership, context={"request": request}).data, status=status.HTTP_201_CREATED)


class MemberDetailView(generics.RetrieveAPIView):
    """A member; an admin changes their role (spec 2.1, D87), and cancels an invitation not yet answered (D90)."""

    permission_classes = [HasActiveOrganization]
    serializer_class = MemberSerializer

    def get_queryset(self):
        return Membership.with_invitations.select_related("user")

    def delete(self, request, pk):
        if request.membership.role != Role.ADMIN:
            raise exceptions.PermissionDenied("only an admin cancels invitations")
        members.cancel_invitation(self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, pk):
        if request.membership.role != Role.ADMIN:
            raise exceptions.PermissionDenied("only an admin changes roles")
        membership = self.get_object()  # another organization's member is not found, whatever the request says
        serializer = MemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = members.set_role(membership, role=serializer.validated_data["role"], actor=request.user)
        return Response(MemberSerializer(membership, context={"request": request}).data)


class InvitationAnswerView(APIView):
    """The person accepts or declines their own invitation (D90); before any organization is open, as after."""

    permission_classes = [IsAuthenticated]
    answers = {"accept": members.accept_invitation, "decline": members.decline_invitation}

    def post(self, request, pk, answer):
        if answer not in self.answers:
            raise exceptions.NotFound("accept or decline")
        try:
            self.answers[answer](request.user, pk)
        except Membership.DoesNotExist as exc:
            raise exceptions.NotFound("no such invitation") from exc
        return Response(session_payload(request))


class PasswordLinkInvalid(exceptions.ValidationError):
    default_code = "password_link_invalid"


class PasswordInvalid(exceptions.ValidationError):
    default_code = "password_invalid"


class ForgotPasswordView(APIView):
    """A link to choose a new password, by email. The answer is the same whether the email has an account."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def initial(self, request, *args, **kwargs):
        SessionAuthentication().enforce_csrf(request)
        super().initial(request, *args, **kwargs)

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        members.forgot_password(serializer.validated_data["email"])
        return Response(
            {"detail": "if this email has an account, a link was sent to it"}, status=status.HTTP_202_ACCEPTED
        )


class SetPasswordView(APIView):
    """The password a person chooses from an invitation's or a reset's link."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def initial(self, request, *args, **kwargs):
        SessionAuthentication().enforce_csrf(request)
        super().initial(request, *args, **kwargs)

    def post(self, request):
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user = members.set_password(data["uid"], data["token"], data["password"])
        except members.PasswordLinkInvalid as exc:
            raise PasswordLinkInvalid("the link is not valid any more: ask for a new one") from exc
        except members.ValidationError as exc:
            raise PasswordInvalid(" ".join(exc.messages)) from exc
        cache.delete_many([login_failures_key(user.email), login_pause_key(user.email)])
        record_password_set(user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def record_password_set(user) -> None:
    """In the audit log of each of the person's organizations: the password was set from a link."""
    from apps.audit.services import record as audit
    from apps.tenancy.context import organization_context

    for membership in Membership.all_organizations.filter(user=user):
        with organization_context(membership.organization_id):
            audit("user.password_set", actor=user, target=membership, payload={"user": user.pk})


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


LOGO_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
LOGO_MAX_BYTES = 1024 * 1024


class IdentityView(APIView):
    """The organization's identity (spec 4.1), carried by its exported files: every member sees it, an admin sets
    it."""

    permission_classes = [HasActiveOrganization]

    def get(self, request):
        return Response(identity_payload(request.organization))

    def patch(self, request):
        if request.membership.role != Role.ADMIN:
            raise exceptions.PermissionDenied("only an admin sets the organization's identity")
        serializer = IdentitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = request.organization
        color = serializer.validated_data["primary_color"].upper()
        colors = {k: v for k, v in (organization.brand_colors or {}).items() if k != "primary"}
        organization.brand_colors = {**colors, **({"primary": color} if color else {})}
        organization.save(update_fields=["brand_colors"])
        record("organization.identity_set", actor=request.user, target=organization, payload={"primary": color})
        return Response(identity_payload(organization))


def _word_takes(image: bytes) -> bool:
    """Whether the Word export can place the image (D80): python-docx reads a JPEG only with a JFIF or Exif header,
    and a logo it cannot read failed every export of the organization."""
    from docx.image.image import Image

    try:
        Image.from_blob(image)
    except Exception:  # noqa: BLE001 - any image python-docx cannot read is refused the same way
        return False
    return True


class IdentityLogoView(APIView):
    """The logo: a PNG or JPEG of at most 1 MB, kept in the file store (task 7.0)."""

    permission_classes = [role_required(Role.ADMIN)]
    parser_classes = [MultiPartParser]
    throttle_classes = [UserRateThrottle, UploadThrottle]

    def post(self, request):
        from apps.files import services as files
        from apps.files.models import File

        if too_long(request, LOGO_MAX_BYTES):
            raise IdentityError("the logo is larger than 1 MB", code="logo_too_large")
        upload = request.FILES.get("file")
        if upload is None:
            raise IdentityError("choose an image", code="file_required")
        if upload.size > LOGO_MAX_BYTES:
            raise IdentityError("the logo is larger than 1 MB", code="logo_too_large")
        data = upload.read()
        content_type = next((kind for magic, kind in LOGO_TYPES.items() if data.startswith(magic)), None)
        if content_type is None or not _word_takes(data):
            raise IdentityError("the logo is a PNG or JPEG image", code="logo_type_unsupported")
        organization = request.organization
        organization.logo_file = files.store(
            data, name=upload.name, content_type=content_type, kind=File.Kind.LOGO, actor=request.user
        )
        organization.save(update_fields=["logo_file"])
        record(
            "organization.logo_set",
            actor=request.user,
            target=organization,
            payload={"file": organization.logo_file_id},
        )
        return Response(identity_payload(organization))

    def delete(self, request):
        organization = request.organization
        organization.logo_file = None
        organization.save(update_fields=["logo_file"])
        record("organization.logo_removed", actor=request.user, target=organization)
        return Response(identity_payload(organization))
