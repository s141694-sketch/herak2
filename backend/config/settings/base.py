"""Settings shared by every environment. Environment-specific values come from the environment."""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    LOG_LEVEL=(str, "INFO"),
    LOG_JSON=(bool, True),
    SENTRY_DSN=(str, ""),
    SENTRY_ENVIRONMENT=(str, "development"),
    SESSION_COOKIE_AGE=(int, 8 * 60 * 60),
    LOGIN_THROTTLE_RATE=(str, "10/minute"),
    # Proxies in front of Django that add to X-Forwarded-For (nginx, as shipped): rate limits count the address the
    # nearest of them saw, so a client cannot pick its own. 0 when Django is reached directly.
    NUM_PROXIES=(int, 1),
    FILES_BUCKET=(str, "harak2-files"),
    FILES_ENDPOINT_URL=(str, ""),
    FILES_PUBLIC_ENDPOINT_URL=(str, ""),
    FILES_ACCESS_KEY_ID=(str, ""),
    FILES_SECRET_ACCESS_KEY=(str, ""),
    FILES_REGION=(str, "us-east-1"),
    FILES_LINK_SECONDS=(int, 60),
    FILES_CREATE_BUCKET=(bool, False),
    COLLAB_TOKEN_TTL_SECONDS=(int, 120),
    COLLAB_INTERNAL_URL=(str, "http://127.0.0.1:1234"),
    COLLAB_TIMEOUT_SECONDS=(float, 10.0),
    COLLAB_SNAPSHOT_TIMEOUT_SECONDS=(float, 3.0),
    AI_PROVIDER=(str, "claude"),
    CELERY_TASK_ALWAYS_EAGER=(bool, False),
    AI_MODEL=(str, "claude-opus-5-5"),
    AI_TIMEOUT_SECONDS=(float, 60.0),
    AI_MAX_ATTEMPTS=(int, 3),
    AI_BACKOFF_SECONDS=(float, 1.0),
    AI_MONTHLY_TOKEN_QUOTA=(int, 2_000_000),
    AI_RECORDINGS_DIR=(str, ""),
    QUALITY_AI_DELAY_SECONDS=(int, 60),
    QUALITY_STALE_RUN_MINUTES=(int, 30),
    COLLAB_SAVE_MAX_BYTES=(int, 64 * 1024 * 1024),
    APP_URL=(str, "http://localhost:5173"),
    FIELD_ENCRYPTION_KEYS=(list, []),
    SSO_ALLOW_HTTP_ISSUERS=(bool, False),
    SSO_ALLOW_PRIVATE_ADDRESSES=(bool, False),
    SSO_CALLBACK_URL=(str, ""),
    DEFAULT_FROM_EMAIL=(str, "Harak <no-reply@localhost>"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.core",
    "apps.accounts",
    "apps.tenancy",
    "apps.audit",
    "apps.competencies",
    "apps.structures",
    "apps.programs",
    "apps.collab",
    "apps.comments",
    "apps.quality",
    "apps.ai",
    "apps.evals",
    "apps.agents",
    "apps.suggestions",
    "apps.workflows",
    "apps.notifications",
    "apps.sso",
    "apps.files",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenancy.middleware.OrganizationContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

REDIS_URL = env("REDIS_URL")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
# Tasks run inside the request that queued them only where no worker runs (the browser tests).
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER")
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE: dict = {
    # Reminders and escalation (spec 6.3): every 15 minutes is well within a work day's precision.
    "workflow-deadlines": {"task": "workflows.check_deadlines", "schedule": crontab(minute="*/15")},
    # The daily digest at 07:00 in Muscat (03:00 UTC).
    "notification-digest": {"task": "notifications.daily_digest", "schedule": crontab(hour=3, minute=0)},
}

# Email (D59): any SMTP provider, from EMAIL_URL (e.g. smtp+tls://user:password@host:587); the console by default.
# Keep credentials in the environment, never in git. Django 6.1 configures mailers with MAILERS (the EMAIL_*
# settings are deprecated).
_email = env.email_url("EMAIL_URL", default="consolemail://")
_smtp = {
    "host": _email.get("EMAIL_HOST"),
    "port": _email.get("EMAIL_PORT"),
    "username": _email.get("EMAIL_HOST_USER"),
    "password": _email.get("EMAIL_HOST_PASSWORD"),
    "use_tls": _email.get("EMAIL_USE_TLS"),
    "use_ssl": _email.get("EMAIL_USE_SSL"),
    "timeout": 20,
}
MAILERS = {
    "default": {
        "BACKEND": _email["EMAIL_BACKEND"],
        "OPTIONS": (
            {k: v for k, v in _smtp.items() if v not in (None, "")}
            if _email["EMAIL_BACKEND"].endswith(".smtp.EmailBackend")
            else {}
        ),
    }
}
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
# Where links in emails lead: the web client, which asks for a sign-in.
APP_URL = env("APP_URL")

# Encryption of stored secrets (identity providers' client secrets, TOTP secrets; spec 7.4, D64): Fernet keys,
# the first encrypts and all decrypt, so a new key can be put first and the old ones kept until re-encrypted.
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEYS = env("FIELD_ENCRYPTION_KEYS")

# Identity providers are reached over https; plain http only for a local Keycloak in development and tests.
SSO_ALLOW_HTTP_ISSUERS = env("SSO_ALLOW_HTTP_ISSUERS")
# Whether a provider may be on this server's own network (a local Keycloak in development and tests); in production
# the server never makes a request to a loopback, private, link-local or metadata address for a provider.
SSO_ALLOW_PRIVATE_ADDRESSES = env("SSO_ALLOW_PRIVATE_ADDRESSES")
# Where providers send the browser back; by default the web client's address, which forwards /api to Django.
SSO_CALLBACK_URL = env("SSO_CALLBACK_URL")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ar"
LANGUAGES = [("ar", "العربية"), ("en", "English")]
TIME_ZONE = "Asia/Muscat"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

COMPETENCY_IMPORT_MAX_BYTES = 2 * 1024 * 1024
COMPETENCY_IMPORT_MAX_ROWS = 2000
BLOCK_CONTENT_MAX_BYTES = 256 * 1024

# Collaboration service: user tokens are signed with one secret, service-to-service calls carry another.
COLLAB_TOKEN_SECRET = env("COLLAB_TOKEN_SECRET")
COLLAB_SERVICE_SECRET = env("COLLAB_SERVICE_SECRET")
COLLAB_TOKEN_TTL_SECONDS = env("COLLAB_TOKEN_TTL_SECONDS")
COLLAB_INTERNAL_URL = env("COLLAB_INTERNAL_URL")
COLLAB_TIMEOUT_SECONDS = env("COLLAB_TIMEOUT_SECONDS")
# Readers of a live draft's rows (comparison, analysis) wait this long for its latest content, then read the rows.
COLLAB_SNAPSHOT_TIMEOUT_SECONDS = env("COLLAB_SNAPSHOT_TIMEOUT_SECONDS")
# A live save carries the whole document twice (rows and Yjs state); it has its own limit (internal endpoint only).
COLLAB_SAVE_MAX_BYTES = env("COLLAB_SAVE_MAX_BYTES")
# The collaboration service calls Django directly over the private network, not through the TLS proxy.
SECURE_REDIRECT_EXEMPT = [r"^api/internal/"]

# AI gateway (apps.ai, decision D37). The provider needs ANTHROPIC_API_KEY in the environment; without it,
# or with AI_PROVIDER empty, the product runs on rules only. The key is read by the SDK, never stored here.
AI_PROVIDER = env("AI_PROVIDER")
AI_MODEL = env("AI_MODEL")
AI_TIMEOUT_SECONDS = env("AI_TIMEOUT_SECONDS")
AI_MAX_ATTEMPTS = env("AI_MAX_ATTEMPTS")
AI_BACKOFF_SECONDS = env("AI_BACKOFF_SECONDS")
AI_MONTHLY_TOKEN_QUOTA = env("AI_MONTHLY_TOKEN_QUOTA")
AI_RECORDINGS_DIR = env("AI_RECORDINGS_DIR")
# A light quality run asks the AI layer only after edits pause this long (cost control, spec 5.4).
QUALITY_AI_DELAY_SECONDS = env("QUALITY_AI_DELAY_SECONDS")
# A run still "running" after this long lost its worker; it may be asked for again, even after submission.
QUALITY_STALE_RUN_MINUTES = env("QUALITY_STALE_RUN_MINUTES")
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
AUTH_USER_MODEL = "accounts.User"

SESSION_COOKIE_AGE = env("SESSION_COOKIE_AGE")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "600/minute", "anon": "60/minute", "login": env("LOGIN_THROTTLE_RATE")},
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    "NUM_PROXIES": env("NUM_PROXIES"),
}

from config.logging import configure_logging  # noqa: E402

LOGGING = configure_logging(json_output=env("LOG_JSON"), level=env("LOG_LEVEL"))

SENTRY_DSN = env("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        traces_sample_rate=0.0,
    )

# Stored files (spec 3 storage, 7.4; D75): an S3-compatible store. The endpoint is empty for the cloud provider's
# own; FILES_PUBLIC_ENDPOINT_URL is the address browsers reach when it differs (compose). Keys may be empty where
# the platform gives the server its own credentials. Links last FILES_LINK_SECONDS.
FILES_BUCKET = env("FILES_BUCKET")
FILES_ENDPOINT_URL = env("FILES_ENDPOINT_URL")
FILES_PUBLIC_ENDPOINT_URL = env("FILES_PUBLIC_ENDPOINT_URL")
FILES_ACCESS_KEY_ID = env("FILES_ACCESS_KEY_ID")
FILES_SECRET_ACCESS_KEY = env("FILES_SECRET_ACCESS_KEY")
FILES_REGION = env("FILES_REGION")
FILES_LINK_SECONDS = env("FILES_LINK_SECONDS")
FILES_CREATE_BUCKET = env("FILES_CREATE_BUCKET")
