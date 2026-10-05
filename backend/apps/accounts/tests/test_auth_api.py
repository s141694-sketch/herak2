import pyotp
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
    assert body["user"] == {
        "id": world["single"].pk,
        "email": "single@example.com",
        "full_name": "سارة",
        "mfa_enabled": False,
    }
    assert body["organization"] == {"id": world["a"].pk, "name": "مركز أ", "slug": "a", "role": "author"}
    assert body["memberships"] == [
        {
            "organization": {"id": world["a"].pk, "name": "مركز أ", "slug": "a"},
            "role": "author",
            "sso_required": False,
            "password_required": False,
            "mfa_required": False,
        },
    ]
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


def test_an_admin_sets_the_organizations_sign_in_rules(world):
    admin = APIClient()
    login(admin, "multi@example.com")
    admin.post("/api/auth/switch-organization/", {"organization_id": world["a"].pk}, format="json")
    # Requiring a second factor of managers needs one in this admin's own session first, or it would lock them out.
    unsafe = admin.patch("/api/organizations/current/", {"mfa_required_for_managers": True}, format="json")
    assert unsafe.status_code == 409 and unsafe.json()["error"]["code"] == "mfa_enable_first"
    secret = admin.post("/api/auth/mfa/enrol/").json()["secret"]
    admin.post("/api/auth/mfa/confirm/", {"code": pyotp.TOTP(secret).now()}, format="json")
    changed = admin.patch(
        "/api/organizations/current/", {"mfa_required_for_managers": True, "sso_session_hours": 4}, format="json"
    )
    assert changed.status_code == 200, changed.content
    assert (changed.json()["mfa_required_for_managers"], changed.json()["sso_session_hours"]) == (True, 4)
    for bad in (
        {"sso_session_hours": 0},
        {"sso_session_hours": 169},
        {"mfa_required_for_managers": "yes"},
        {"name": "x"},
    ):
        assert admin.patch("/api/organizations/current/", bad, format="json").status_code == 400, bad
    author = APIClient()
    login(author, "single@example.com")
    assert author.patch("/api/organizations/current/", {"sso_session_hours": 2}, format="json").status_code == 403


def test_a_client_cannot_choose_the_address_its_sign_in_attempts_are_counted_by():
    """Behind the proxy (one, as shipped), only the address the proxy saw counts: a forged X-Forwarded-For entry
    does not buy a fresh allowance (from the independent review of phase 6)."""
    from django.core.cache import cache

    cache.clear()
    client = APIClient()
    statuses = [
        client.post(
            "/api/auth/login/",
            {"email": "nobody@example.test", "password": "wrong"},
            format="json",
            HTTP_X_FORWARDED_FOR=f"10.9.9.{i}, 192.0.2.7",
        ).status_code
        for i in range(12)
    ]
    assert statuses[-1] == 429
