from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.audit.services import record
from apps.tenancy.context import current_organization_id
from apps.tenancy.permissions import HasActiveOrganization

from .gateway import used_this_month
from .models import AIPolicy
from .serializers import AIPolicySerializer


def _describe(policy: AIPolicy | None, organization_id: int) -> dict:
    from django.conf import settings

    quota = policy.quota if policy else settings.AI_MONTHLY_TOKEN_QUOTA
    return {
        "id": organization_id,
        "mode": policy.mode if policy else AIPolicy.Mode.AI,
        "monthly_token_quota": quota,
        "used_this_month": used_this_month(organization_id),
    }


class AIPolicyView(APIView):
    """The active organization's AI policy: rules-only mode and monthly quota (spec 5.1.4, 5.4). Admins change it."""

    permission_classes = [HasActiveOrganization]

    def get(self, request):
        organization_id = current_organization_id()
        return Response(_describe(AIPolicy.objects.first(), organization_id))

    def put(self, request):
        if request.membership.role != Role.ADMIN:
            raise exceptions.PermissionDenied("only an organization admin changes the AI policy")
        serializer = AIPolicySerializer(AIPolicy.objects.first(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        record(
            "ai.policy_changed",
            actor=request.user,
            target=policy,
            payload={"mode": policy.mode, "monthly_token_quota": policy.monthly_token_quota},
        )
        return Response(_describe(policy, current_organization_id()))
