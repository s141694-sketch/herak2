from .base import *  # noqa: F403

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

for _name in ("SECRET_KEY", "COLLAB_TOKEN_SECRET", "COLLAB_SERVICE_SECRET"):
    if len(globals()[_name]) < 32 or "change-me" in globals()[_name]:
        raise ImproperlyConfigured(f"{_name} must be a random value of at least 32 characters")

# Stored secrets (D64) and identity providers (spec 7.2): nothing meant for development or tests.
from cryptography.fernet import Fernet  # noqa: E402

from .public_keys import PUBLIC_FIELD_KEYS  # noqa: E402

for _key in (k.strip() for k in FIELD_ENCRYPTION_KEYS if k and k.strip()):  # noqa: F405
    if _key in PUBLIC_FIELD_KEYS:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS holds a development or test key from git")
    try:
        Fernet(_key)
    except ValueError as _exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS holds a value that is not a Fernet key") from _exc
for _name in ("SSO_ALLOW_HTTP_ISSUERS", "SSO_ALLOW_PRIVATE_ADDRESSES"):
    if globals()[_name]:
        raise ImproperlyConfigured(f"{_name} is for a local test provider, never production")
