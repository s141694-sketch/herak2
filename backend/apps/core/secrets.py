"""Encryption of stored secrets (spec 7.4, D64): identity providers' client secrets and TOTP secrets.

Fernet keys come from FIELD_ENCRYPTION_KEYS; the first encrypts and every key decrypts, so keys can be rotated.
Without a key nothing secret can be stored, and the caller says so plainly.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

from .errors import Conflict


class EncryptionUnavailable(Conflict):
    default_code = "encryption_not_configured"
    default_detail = "no encryption key is configured on this server"


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings.FIELD_ENCRYPTION_KEYS if k and k.strip()]
    if not keys:
        raise EncryptionUnavailable()
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as exc:
        raise EncryptionUnavailable("a configured encryption key is not a valid key") from exc


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailable("a stored secret cannot be read with the configured keys") from exc


def rotate(token: str) -> str:
    """The same secret, encrypted again with the first key, so older keys can be retired."""
    try:
        return _fernet().rotate(token.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailable("a stored secret cannot be read with the configured keys") from exc
