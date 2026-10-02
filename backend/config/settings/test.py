import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("DATABASE_URL", "postgres://harak:harak@127.0.0.1:54329/harak")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/1")
os.environ.setdefault("LOG_JSON", "False")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from .base import *  # noqa: E402, F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.tenancy.tests.testapp"]  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
