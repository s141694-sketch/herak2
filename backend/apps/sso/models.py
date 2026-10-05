"""An organization's single sign-on (spec 4.1, 7.2): the email domains it proved it owns, its OIDC provider, and
the identities that provider vouched for."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core import secrets
from apps.tenancy.models import OrganizationScopedModel

RECORD_PREFIX = "_harak2-verification"
VALUE_PREFIX = "harak2-verification="


class VerifiedDomain(OrganizationScopedModel):
    """An email domain; verified once its DNS TXT record carried the token (D63)."""

    domain = models.CharField(max_length=253)
    token = models.CharField(max_length=64)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["domain"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "domain"], name="sso_domain_once_per_organization"),
            # A domain belongs to one organization at most, across all of them.
            models.UniqueConstraint(
                fields=["domain"], condition=Q(verified_at__isnull=False), name="sso_domain_verified_once"
            ),
        ]

    @property
    def record_name(self) -> str:
        return f"{RECORD_PREFIX}.{self.domain}"

    @property
    def record_value(self) -> str:
        return f"{VALUE_PREFIX}{self.token}"

    def __str__(self) -> str:
        return self.domain


class IdentityProviderConfig(OrganizationScopedModel):
    """The organization's OIDC provider. The client secret is stored encrypted (spec 7.4) and never returned."""

    issuer = models.URLField(max_length=500)
    client_id = models.CharField(max_length=255)
    client_secret_encrypted = models.TextField()
    # Members of the organization's verified domains may sign in through it.
    enabled = models.BooleanField(default=False)
    # Passwords no longer open the organization's context, except for the emergency account (D66).
    enforced = models.BooleanField(default=False)
    emergency_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    config_changed_at = models.DateTimeField()
    # The last successful checks since the last change (spec 7.2: tested before enforcement).
    discovery_ok_at = models.DateTimeField(null=True, blank=True)
    test_login_ok_at = models.DateTimeField(null=True, blank=True)
    last_test_error = models.TextField(blank=True)
    last_test_error_code = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization"], name="sso_one_provider_per_organization")]

    @property
    def client_secret(self) -> str:
        return secrets.decrypt(self.client_secret_encrypted)

    @client_secret.setter
    def client_secret(self, value: str) -> None:
        self.client_secret_encrypted = secrets.encrypt(value)

    @property
    def tested(self) -> bool:
        """Connection test and a test sign-in both succeeded since the last change."""
        return bool(self.discovery_ok_at and self.test_login_ok_at)

    def __str__(self) -> str:
        return self.issuer


class ExternalIdentity(OrganizationScopedModel):
    """A person as the organization's provider knows them (issuer and subject), so a changed email still finds them."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="external_identities")
    issuer = models.CharField(max_length=500)
    subject = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "issuer", "subject"], name="sso_identity_once")]

    def __str__(self) -> str:
        return f"{self.issuer} {self.subject}"
