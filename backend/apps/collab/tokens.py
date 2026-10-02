"""Short-lived tokens that let one browser open one live document on the collaboration service (spec 6.6)."""

import time

import jwt
from django.conf import settings

ISSUER = "harak2-api"
AUDIENCE = "harak2-collab"
ALGORITHM = "HS256"


def document_name(version) -> str:
    return f"program-version:{version.pk}"


def issue(*, version, user, writable: bool) -> dict:
    now = int(time.time())
    ttl = settings.COLLAB_TOKEN_TTL_SECONDS
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user.pk),
        "org": version.organization_id,
        "ver": version.pk,
        "doc": document_name(version),
        "mode": "write" if writable else "read",
        "name": user.full_name or user.email,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(claims, settings.COLLAB_TOKEN_SECRET, algorithm=ALGORITHM)
    return {"token": token, "document": claims["doc"], "mode": claims["mode"], "expires_in": ttl}


def decode_for_tests(token: str) -> dict:
    return jwt.decode(token, settings.COLLAB_TOKEN_SECRET, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER)
