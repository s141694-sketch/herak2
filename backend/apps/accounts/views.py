from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import exceptions, generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.tenancy.middleware import SESSION_KEY, memberships_of
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

    @ensure_csrf_cookie
    def get(self, request):
        return Response({"detail": "ok"})


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = authenticate(request, username=email, password=serializer.validated_data["password"])
        if user is None:
            raise InvalidCredentials("invalid email or password")
        login(request, user)
        memberships = list(memberships_of(user))
        _select_membership(request, memberships[0] if len(memberships) == 1 else None)
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
        membership = memberships_of(request.user).filter(organization_id=serializer.validated_data["organization_id"]).first()
        if membership is None:
            raise exceptions.NotFound("no membership in that organization")
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
