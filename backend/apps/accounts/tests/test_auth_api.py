import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def world():
    a = Organization.objects.create(name="مركز أ", slug="a")
    b = Organization.objects.create(name="مركز ب", slug="b")
    multi = User.objects.create_user(email="multi@example.com", password=PASSWORD, full_name="مازن")
    single = User.objects.create_user(email="single@example.com", password=PASSWORD, full_name="سارة")
    pending = User.objects.create_user(email="pending@example.com", password=PASSWORD)
    outsider = User.objects.create_user(email="outsider@example.com", password=PASSWORD)
    with organization_context(a):
        Membership.objects.create(user=multi, role=Role.ADMIN)
        Membership.objects.create(user=single, role=Role.AUTHOR)
        Membership.objects.create(user=pending, role=Role.PENDING)
    with organization_context(b):
        Membership.objects.create(user=multi, role=Role.REVIEWER)
    return {"a": a, "b": b, "multi": multi, "single": single, "pending": pending, "outsider": outsider}


def login(client: APIClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login/", {"email": email, "password": password}, format="json")


def test_login_with_a_single_membership_selects_that_organization(world):
    client = APIClient()
    response = login(client, "single@example.com")
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": world["single"].pk, "email": "single@example.com", "full_name": "سارة"}
    assert body["organization"] == {"id": world["a"].pk, "name": "مركز أ", "slug": "a", "role": "author"}
    assert body["memberships"] == [{"organization": {"id": world["a"].pk, "name": "مركز أ", "slug": "a"}, "role": "author"}]
    assert "sessionid" in response.cookies


def test_login_with_several_memberships_requires_a_choice(world):
    client = APIClient()
    body = login(client, "multi@example.com").json()
    assert body["organization"] is None
    assert [m["organization"]["slug"] for m in body["memberships"]] == ["a", "b"]


def test_login_email_is_case_insensitive(world):
    assert login(APIClient(), "  Single@Example.com ").status_code == 200


@pytest.mark.parametrize("email,password", [("single@example.com", "wrong"), ("nobody@example.com", PASSWORD)])
def test_wrong_credentials_get_one_generic_error(world, email, password):
    response = login(APIClient(), email, password)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_inactive_user_cannot_log_in(world):
    world["single"].is_active = False
    world["single"].save()
    assert login(APIClient(), "single@example.com").json()["error"]["code"] == "invalid_credentials"


def test_me_requires_authentication(world):
    assert APIClient().get("/api/auth/me/").status_code == 403


def test_logout_ends_the_session(world):
    client = APIClient()
    login(client, "single@example.com")
    assert client.get("/api/auth/me/").status_code == 200
    assert client.post("/api/auth/logout/").status_code == 204
    assert client.get("/api/auth/me/").status_code == 403


def test_switching_organization_changes_the_context(world):
    client = APIClient()
    login(client, "multi@example.com")
    assert client.get("/api/organizations/current/").status_code == 409  # no organization chosen yet

    response = client.post("/api/auth/switch-organization/", {"organization_id": world["b"].pk}, format="json")
    assert response.status_code == 200
    assert response.json()["organization"]["slug"] == "b"
    assert client.get("/api/organizations/current/").json()["slug"] == "b"
    assert client.get("/api/auth/me/").json()["organization"]["role"] == "reviewer"

    response = client.post("/api/auth/switch-organization/", {"organization_id": world["a"].pk}, format="json")
    assert response.json()["organization"]["role"] == "admin"
    assert client.get("/api/organizations/current/").json()["slug"] == "a"


def test_switching_to_an_organization_without_membership_is_not_found(world):
    client = APIClient()
    login(client, "single@example.com")
    for organization_id in (world["b"].pk, 999999):
        response = client.post("/api/auth/switch-organization/", {"organization_id": organization_id}, format="json")
        assert response.status_code == 404
    assert client.get("/api/organizations/current/").json()["slug"] == "a"


def test_members_are_listed_for_the_current_organization_only(world):
    client = APIClient()
    login(client, "multi@example.com")
    client.post("/api/auth/switch-organization/", {"organization_id": world["a"].pk}, format="json")
    emails = sorted(m["user"]["email"] for m in client.get("/api/organizations/current/members/").json())
    assert emails == ["multi@example.com", "pending@example.com", "single@example.com"]

    client.post("/api/auth/switch-organization/", {"organization_id": world["b"].pk}, format="json")
    emails = [m["user"]["email"] for m in client.get("/api/organizations/current/members/").json()]
    assert emails == ["multi@example.com"]


def test_pending_members_have_no_access_to_organization_data(world):
    client = APIClient()
    body = login(client, "pending@example.com").json()
    assert body["organization"]["role"] == "pending"
    assert client.get("/api/organizations/current/").status_code == 403
    assert client.get("/api/organizations/current/members/").status_code == 403


def test_outsider_has_no_organization(world):
    client = APIClient()
    assert login(client, "outsider@example.com").json()["organization"] is None
    assert client.get("/api/organizations/current/").status_code == 409


def test_login_attempts_are_rate_limited(world):
    cache.clear()
    client = APIClient()
    statuses = [login(client, "single@example.com", "wrong").status_code for _ in range(11)]
    assert statuses[:10] == [400] * 10
    assert statuses[10] == 429
    cache.clear()
