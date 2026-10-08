"""Stored secrets are encrypted with the configured keys (D64)."""

import pytest
from cryptography.fernet import Fernet

from apps.core import secrets


def test_a_secret_round_trips_and_is_not_stored_in_clear():
    token = secrets.encrypt("client-secret-value")
    assert "client-secret-value" not in token
    assert secrets.decrypt(token) == "client-secret-value"


def test_keys_rotate_the_first_encrypts_all_decrypt(settings):
    old = secrets.encrypt("s")
    settings.FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode(), *settings.FIELD_ENCRYPTION_KEYS]
    assert secrets.decrypt(old) == "s"
    new = secrets.encrypt("t")
    settings.FIELD_ENCRYPTION_KEYS = settings.FIELD_ENCRYPTION_KEYS[1:]
    with pytest.raises(secrets.EncryptionUnavailable):
        secrets.decrypt(new)


def test_without_a_key_nothing_secret_is_stored(settings):
    settings.FIELD_ENCRYPTION_KEYS = [""]
    with pytest.raises(secrets.EncryptionUnavailable) as refused:
        secrets.encrypt("s")
    assert refused.value.get_codes() == "encryption_not_configured"


# --- From the independent review of phase 6 -----------------------------------------------------------------


def test_a_key_that_is_not_a_key_is_refused_plainly(settings):
    settings.FIELD_ENCRYPTION_KEYS = ["not-a-fernet-key"]
    with pytest.raises(secrets.EncryptionUnavailable) as refused:
        secrets.encrypt("s")
    assert refused.value.get_codes() == "encryption_not_configured"


@pytest.mark.django_db
def test_rotation_re_encrypts_every_stored_secret_with_the_first_key(settings):
    from django.core.management import call_command

    from apps.accounts.models import Organization, TOTPDevice, User
    from apps.sso.models import IdentityProviderConfig
    from apps.tenancy.context import organization_context

    old = settings.FIELD_ENCRYPTION_KEYS[0]
    user = User.objects.create_user(email="a@example.com", password=None)
    TOTPDevice.objects.create(user=user, secret_encrypted=secrets.encrypt("totp-secret"))
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        from django.utils import timezone

        config = IdentityProviderConfig(issuer="https://idp.example", client_id="c", config_changed_at=timezone.now())
        config.client_secret = "client-secret"
        config.save()
    new = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [new, old]
    call_command("rotate_field_encryption")
    settings.FIELD_ENCRYPTION_KEYS = [new]  # the old key is retired
    assert secrets.decrypt(TOTPDevice.objects.get(user=user).secret_encrypted) == "totp-secret"
    assert IdentityProviderConfig.all_organizations.get(pk=config.pk).client_secret == "client-secret"


@pytest.mark.parametrize(
    "environment,problem",
    [
        ({"FIELD_ENCRYPTION_KEYS": "ZGV2LW9ubHktZmllbGQtZW5jcnlwdGlvbi1rZXktMDE="}, "FIELD_ENCRYPTION_KEYS"),
        ({"FIELD_ENCRYPTION_KEYS": "not-a-key"}, "FIELD_ENCRYPTION_KEYS"),
        # Without a key, two-factor sign-in and identity providers fail at first use (phase 8 review).
        ({"FIELD_ENCRYPTION_KEYS": ""}, "FIELD_ENCRYPTION_KEYS"),
        ({"SSO_ALLOW_HTTP_ISSUERS": "True"}, "SSO_ALLOW_HTTP_ISSUERS"),
        ({"SSO_ALLOW_PRIVATE_ADDRESSES": "True"}, "SSO_ALLOW_PRIVATE_ADDRESSES"),
    ],
)
def test_production_refuses_to_start_with_development_settings_for_secrets_and_providers(environment, problem):
    import os
    import subprocess
    import sys

    good = {
        "SECRET_KEY": "p" * 40,
        "COLLAB_TOKEN_SECRET": "q" * 40,
        "COLLAB_SERVICE_SECRET": "r" * 40,
        "DATABASE_URL": "postgres://u:p@localhost:5432/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "ALLOWED_HOSTS": "harak.example",
        "FIELD_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
    }
    base = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "VIRTUAL_ENV", "PYTHONPATH")}
    run = [sys.executable, "-c", "import config.settings.production"]
    assert subprocess.run(run, env={**base, **good}, capture_output=True, text=True).returncode == 0
    refused = subprocess.run(run, env={**base, **good, **environment}, capture_output=True, text=True)
    assert refused.returncode != 0 and "ImproperlyConfigured" in refused.stderr and problem in refused.stderr
