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
