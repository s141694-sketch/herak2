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
