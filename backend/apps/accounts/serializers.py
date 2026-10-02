from rest_framework import serializers

from .models import Membership, Organization, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name"]


class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug"]


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationSummarySerializer()

    class Meta:
        model = Membership
        fields = ["organization", "role"]


class MemberSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "created_at"]


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "brand_colors",
            "work_days",
            "pre_submit_critical_behavior",
            "ai_enabled",
            "ai_monthly_quota",
            "sso_session_hours",
            "reminder_before_due_work_days",
            "escalation_delay_work_days",
        ]


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


class SwitchOrganizationSerializer(serializers.Serializer):
    organization_id = serializers.IntegerField()


def session_payload(request) -> dict:
    """The shape returned by login, me and switch: who you are, where you are, where you could be."""
    memberships = list(
        Membership.all_organizations.filter(user=request.user)
        .select_related("organization")
        .order_by("organization__name")
    )
    active = getattr(request, "membership", None)
    return {
        "user": UserSerializer(request.user).data,
        "organization": (
            {**OrganizationSummarySerializer(active.organization).data, "role": active.role} if active else None
        ),
        "memberships": MembershipSerializer(memberships, many=True).data,
    }
