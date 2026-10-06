from rest_framework import serializers

from apps.tenancy.middleware import entry_refusal

from .models import Membership, Organization, Role, TOTPDevice, User


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

    def to_representation(self, membership):
        data = super().to_representation(membership)
        request = self.context.get("request")
        viewer = getattr(request, "membership", None)
        if viewer is not None and viewer.role == Role.ADMIN:
            # An admin resets a lost second factor (D67): they see who has one; other members do not.
            data["mfa_enabled"] = TOTPDevice.objects.filter(user=membership.user, confirmed_at__isnull=False).exists()
        return data


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
            "mfa_required_for_managers",
            "reminder_before_due_work_days",
            "escalation_delay_work_days",
        ]


class SignInRulesSerializer(serializers.ModelSerializer):
    """What an admin sets about signing in to the organization (spec 4.1, 7.1, 7.2); nothing else is writable here."""

    sso_session_hours = serializers.IntegerField(min_value=1, max_value=168, required=False)
    mfa_required_for_managers = serializers.BooleanField(required=False)

    class Meta:
        model = Organization
        fields = ["sso_session_hours", "mfa_required_for_managers"]

    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields) if isinstance(data, dict) else set()
        if unknown:
            raise serializers.ValidationError({key: "not settable here" for key in unknown})
        if isinstance(data, dict) and "mfa_required_for_managers" in data:
            if not isinstance(data["mfa_required_for_managers"], bool):
                raise serializers.ValidationError({"mfa_required_for_managers": "true or false"})
        return super().to_internal_value(data)


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
        "user": {
            **UserSerializer(request.user).data,
            "mfa_enabled": TOTPDevice.objects.filter(user=request.user, confirmed_at__isnull=False).exists(),
        },
        "organization": (
            {**OrganizationSummarySerializer(active.organization).data, "role": active.role} if active else None
        ),
        # Whether each organization asks this session for its provider (D66), a password (D71) or a second factor
        # (D67) first.
        "memberships": [
            {
                **data,
                "sso_required": (refusal := entry_refusal(request, membership)) == "sso_required",
                "password_required": refusal == "password_required",
                "mfa_required": refusal == "mfa_required",
            }
            for membership, data in zip(memberships, MembershipSerializer(memberships, many=True).data, strict=True)
        ],
    }
