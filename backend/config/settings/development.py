import os

from .public_keys import DEVELOPMENT_FIELD_KEY

os.environ.setdefault("SECRET_KEY", "dev-only-secret-key-change-me")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("DATABASE_URL", "postgres://harak:harak@127.0.0.1:5432/harak")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("LOG_JSON", "False")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://localhost:5173")

os.environ.setdefault("COLLAB_TOKEN_SECRET", "dev-only-collab-token-secret-change-me")
os.environ.setdefault("COLLAB_SERVICE_SECRET", "dev-only-collab-service-secret-change-me")

os.environ.setdefault("SSO_ALLOW_HTTP_ISSUERS", "True")  # the local Keycloak (D62)
os.environ.setdefault("SSO_ALLOW_PRIVATE_ADDRESSES", "True")  # the local Keycloak (D62)
# A development-only key; production takes its keys from the environment and refuses this one (D64).
os.environ.setdefault("FIELD_ENCRYPTION_KEYS", DEVELOPMENT_FIELD_KEY)

# Files go to a local S3-compatible store: moto's server (frontend/e2e starts it on port 5059), or MinIO (D75).
os.environ.setdefault("FILES_ENDPOINT_URL", "http://127.0.0.1:5059")
os.environ.setdefault("FILES_ACCESS_KEY_ID", "dev-only")
os.environ.setdefault("FILES_SECRET_ACCESS_KEY", "dev-only")
os.environ.setdefault("FILES_CREATE_BUCKET", "True")

from .base import *  # noqa: E402, F403
