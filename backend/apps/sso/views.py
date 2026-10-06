from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import Membership, Role
from apps.tenancy.permissions import role_required

from . import login as sso_login
from . import services
from .models import IdentityProviderConfig, VerifiedDomain
from .serializers import IdentityProviderSerializer, VerifiedDomainSerializer

AdminOnly = role_required(Role.ADMIN)


def _text(data, key) -> str:
    value = data.get(key, "") if isinstance(data, dict) else ""
    if not isinstance(value, str):
        raise exceptions.ValidationError({key: "a text"})
    return value


class DomainListView(generics.ListAPIView):
    permission_classes = [AdminOnly]
    serializer_class = VerifiedDomainSerializer

    def get_queryset(self):
        return VerifiedDomain.objects.all()

    def post(self, request):
        domain = services.add_domain(_text(request.data, "domain"), actor=request.user)
        return Response(VerifiedDomainSerializer(domain).data, status=status.HTTP_201_CREATED)


class DomainDetailView(generics.RetrieveAPIView):
    permission_classes = [AdminOnly]
    serializer_class = VerifiedDomainSerializer

    def get_queryset(self):
        return VerifiedDomain.objects.all()

    def delete(self, request, pk):
        services.remove_domain(self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DomainVerifyView(APIView):
    permission_classes = [AdminOnly]

    def post(self, request, pk):
        domain = services.verify_domain(get_object_or_404(VerifiedDomain.objects, pk=pk), actor=request.user)
        return Response(VerifiedDomainSerializer(domain).data)


def _provider_body(request) -> dict:
    return {key: _text(request.data, key) for key in ("issuer", "client_id", "client_secret")}


class ProviderListView(generics.ListAPIView):
    """The organization's provider, as a list of at most one."""

    permission_classes = [AdminOnly]
    serializer_class = IdentityProviderSerializer

    def get_queryset(self):
        return IdentityProviderConfig.objects.select_related("emergency_user")

    def post(self, request):
        config = services.save_provider(None, actor=request.user, **_provider_body(request))
        return Response(IdentityProviderSerializer(config).data, status=status.HTTP_201_CREATED)


class ProviderDetailView(generics.RetrieveAPIView):
    permission_classes = [AdminOnly]
    serializer_class = IdentityProviderSerializer

    def get_queryset(self):
        return IdentityProviderConfig.objects.select_related("emergency_user")

    def put(self, request, pk):
        config = services.save_provider(self.get_object(), actor=request.user, **_provider_body(request))
        return Response(IdentityProviderSerializer(config).data)


class ProviderTestView(APIView):
    permission_classes = [AdminOnly]

    def post(self, request, pk):
        config = get_object_or_404(IdentityProviderConfig.objects, pk=pk)
        return Response(IdentityProviderSerializer(services.test_connection(config, actor=request.user)).data)


# --- Signing in (tasks 6.5, 6.6) --------------------------------------------------------------------------


class SsoStartThrottle(AnonRateThrottle):
    scope = "login"


class SsoDiscoverView(APIView):
    """Spec 7.2, the path's first step: from the email, whether its domain's organization signs people in through
    a provider. The sign-in page then offers that way first. It says nothing about any person."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [SsoStartThrottle]

    def initial(self, request, *args, **kwargs):
        SessionAuthentication().enforce_csrf(request)
        super().initial(request, *args, **kwargs)

    def post(self, request):
        return Response({"available": sso_login.provider_for_email(_text(request.data, "email")) is not None})


class SsoStartView(APIView):
    """The email decides: its verified domain's organization signs the person in through its provider. A signed-in
    member may instead name one of their organizations, to enter it through its own provider."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [SsoStartThrottle]

    def initial(self, request, *args, **kwargs):
        SessionAuthentication().enforce_csrf(request)  # as the password login: no login CSRF
        super().initial(request, *args, **kwargs)

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        if "organization" in data:
            organization = data["organization"]
            if not isinstance(organization, int) or isinstance(organization, bool):
                raise exceptions.ValidationError({"organization": "an organization id"})
            config = self._provider_of(request, organization)
            email = request.user.email if config is not None else ""
        else:
            email = _text(data, "email")
            config = sso_login.provider_for_email(email)
        if config is None:
            raise sso_login.SsoNotAvailable()
        language = data.get("language")
        return Response({"redirect": sso_login.begin(request, config, email=email, language=language)})

    @staticmethod
    def _provider_of(request, organization_id: int) -> IdentityProviderConfig | None:
        user = request.user
        if (
            not user.is_authenticated
            or not Membership.all_organizations.filter(user=user, organization_id=organization_id).exists()
        ):
            return None
        return IdentityProviderConfig.all_organizations.filter(organization_id=organization_id, enabled=True).first()


class SsoCallbackView(APIView):
    """Where the provider sends the browser back; it always leaves for a page of the web client."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        return HttpResponseRedirect(sso_login.complete(request._request))


class ProviderTestLoginView(APIView):
    """An admin signs in at the provider to prove it works before members rely on it (spec 7.2)."""

    permission_classes = [AdminOnly]

    def post(self, request, pk):
        config = get_object_or_404(IdentityProviderConfig.objects, pk=pk)
        language = request.data.get("language") if isinstance(request.data, dict) else None
        return Response({"redirect": sso_login.begin(request, config, test_by=request.user, language=language)})


class ProviderPolicyView(APIView):
    permission_classes = [AdminOnly]

    def post(self, request, pk):
        config = get_object_or_404(IdentityProviderConfig.objects, pk=pk)
        data = request.data if isinstance(request.data, dict) else {}
        enabled, enforced = data.get("enabled", False), data.get("enforced", False)
        if not isinstance(enabled, bool) or not isinstance(enforced, bool):
            raise exceptions.ValidationError("enabled and enforced are true or false")
        chosen = data.get("emergency_user")
        if chosen is not None and (not isinstance(chosen, int) or isinstance(chosen, bool)):
            raise exceptions.ValidationError({"emergency_user": "a user id or null"})
        emergency = None
        if chosen is not None:
            membership = Membership.objects.filter(user_id=chosen).select_related("user").first()
            if membership is None:
                raise exceptions.ValidationError({"emergency_user": "not a member of this organization"})
            emergency = membership.user
        config = services.set_policy(
            config, actor=request.user, enabled=enabled, enforced=enforced, emergency_user=emergency
        )
        return Response(IdentityProviderSerializer(config).data)
