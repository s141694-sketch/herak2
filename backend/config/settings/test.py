import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("DATABASE_URL", "postgres://harak:harak@127.0.0.1:54329/harak")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/1")
os.environ.setdefault("LOG_JSON", "False")
os.environ.setdefault("LOG_LEVEL", "WARNING")

os.environ.setdefault("COLLAB_TOKEN_SECRET", "test-collab-token-secret-0123456789")
os.environ.setdefault("COLLAB_SERVICE_SECRET", "test-collab-service-secret-0123456789")
# Tests never call a real model; the ones that exercise the gateway give it a provider explicitly.
os.environ.setdefault("AI_PROVIDER", "")
os.environ.setdefault("AI_BACKOFF_SECONDS", "0")
# A test-only key: it protects nothing outside the test database.
os.environ.setdefault("FIELD_ENCRYPTION_KEYS", "dGVzdC1vbmx5LWZpZWxkLWVuY3J5cHRpb24ta2V5LTE=")

from .base import *  # noqa: E402, F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.tenancy.tests.testapp"]  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
