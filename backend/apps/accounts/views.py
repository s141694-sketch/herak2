from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import exceptions, generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.tenancy.middleware import SESSION_KEY, EntryRefused, entry_refusal, memberships_of
from apps.tenancy.permissions import HasActiveOrganization

from .models import Membership
from .serializers import (
    LoginSerializer,
    MemberSerializer,
    OrganizationSerializer,
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
        login(request, user)
        memberships = list(memberships_of(user))
        refusals = [entry_refusal(request, m) for m in memberships]
        open_to_session = [m for m, refusal in zip(memberships, refusals, strict=True) if refusal is None]
        if memberships and not open_to_session:
            # Every organization of this person asks for something a password does not give (D66).
            logout(request)
            raise EntryRefused("sign in through your organization", code=refusals[0])
        _select_membership(request, open_to_session[0] if len(open_to_session) == 1 else None)
        return Response(session_payload(request))


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
