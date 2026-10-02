import os

os.environ.setdefault("SECRET_KEY", "dev-only-secret-key-change-me")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("DATABASE_URL", "postgres://harak:harak@127.0.0.1:5432/harak")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("LOG_JSON", "False")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://localhost:5173")

from .base import *  # noqa: E402, F403
