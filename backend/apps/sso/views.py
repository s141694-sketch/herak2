from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.tenancy.permissions import role_required

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
