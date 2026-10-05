from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import IdentityProviderConfig, VerifiedDomain


class VerifiedDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerifiedDomain
        fields = [
            "id",
            "domain",
            "record_name",
            "record_value",
            "verified_at",
            "last_checked_at",
            "last_error",
            "last_error_code",
            "created_at",
        ]


class IdentityProviderSerializer(serializers.ModelSerializer):
    """The secret is never returned; only whether one is stored."""

    has_secret = serializers.SerializerMethodField()
    emergency_user = UserSerializer(read_only=True)
    tested = serializers.BooleanField(read_only=True)

    class Meta:
        model = IdentityProviderConfig
        fields = [
            "id",
            "issuer",
            "client_id",
            "has_secret",
            "enabled",
            "enforced",
            "emergency_user",
            "config_changed_at",
            "discovery_ok_at",
            "test_login_ok_at",
            "tested",
            "last_test_error",
            "last_test_error_code",
        ]

    def get_has_secret(self, config) -> bool:
        return bool(config.client_secret_encrypted)
