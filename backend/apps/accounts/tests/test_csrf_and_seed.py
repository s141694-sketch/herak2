import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, User

pytestmark = pytest.mark.django_db


def test_login_requires_a_csrf_token():
    User.objects.create_user(email="u@example.com", password="x" * 12)
    client = APIClient(enforce_csrf_checks=True)
    response = client.post("/api/auth/login/", {"email": "u@example.com", "password": "x" * 12}, format="json")
    assert response.status_code == 403

    client.get("/api/auth/csrf/")
    token = client.cookies["csrftoken"].value
    response = client.post(
        "/api/auth/login/", {"email": "u@example.com", "password": "x" * 12}, format="json", HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 200


def test_seed_refuses_to_run_unless_explicitly_allowed(monkeypatch):
    monkeypatch.delenv("HARAK_ALLOW_SEED", raising=False)
    with pytest.raises(CommandError):
        call_command("seed_e2e")


def test_seed_is_idempotent(monkeypatch):
    monkeypatch.setenv("HARAK_ALLOW_SEED", "1")
    call_command("seed_e2e")
    call_command("seed_e2e")
    assert Organization.objects.count() == 2
    assert User.objects.count() == 3
    assert Membership.all_organizations.count() == 4
    roles = set(Membership.all_organizations.filter(user__email="multi@example.com").values_list("role", flat=True))
    assert roles == {"admin", "reviewer"}
