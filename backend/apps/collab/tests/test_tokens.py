import time

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.collab.tokens import decode_for_tests
from apps.programs import lifecycle
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        member("reviewer@example.com", Role.REVIEWER)
        version = program(owner).versions.get()
    return org, owner, version


def test_a_collaborator_gets_a_short_lived_write_token_for_one_document(world):
    org, owner, version = world
    response = login("owner@example.com").post(f"/api/program-versions/{version.pk}/collab-token/")
    assert response.status_code == 200
    body = response.json()
    assert body["document"] == f"program-version:{version.pk}"
    assert body["mode"] == "write"
    assert body["expires_in"] == settings.COLLAB_TOKEN_TTL_SECONDS
    claims = decode_for_tests(body["token"])
    assert claims["doc"] == body["document"]
    assert (claims["sub"], claims["org"], claims["ver"], claims["mode"]) == (str(owner.pk), org.pk, version.pk, "write")
    assert claims["exp"] - claims["iat"] == settings.COLLAB_TOKEN_TTL_SECONDS
    assert claims["aud"] == "harak2-collab" and claims["iss"] == "harak2-api"


def test_non_collaborators_and_locked_versions_get_read_tokens(world):
    org, owner, version = world
    reviewer = login("reviewer@example.com").post(f"/api/program-versions/{version.pk}/collab-token/").json()
    assert reviewer["mode"] == "read"
    with organization_context(org):
        lifecycle.transition(version, ProgramVersion.Status.SUBMITTED, actor=owner)
    locked = login("owner@example.com").post(f"/api/program-versions/{version.pk}/collab-token/").json()
    assert locked["mode"] == "read"


def test_tokens_are_signed_with_the_collab_secret_and_expire(world):
    _, _, version = world
    token = login("owner@example.com").post(f"/api/program-versions/{version.pk}/collab-token/").json()["token"]
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "another-secret-of-the-right-length-0123", algorithms=["HS256"], audience="harak2-collab")
    claims = decode_for_tests(token)
    assert claims["exp"] <= int(time.time()) + settings.COLLAB_TOKEN_TTL_SECONDS
