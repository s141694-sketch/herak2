import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, User
from apps.workflows.models import WorkflowTemplate

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
    assert Organization.objects.count() == 3
    assert User.objects.count() == 8
    assert Membership.all_organizations.count() == 9
    assert WorkflowTemplate.all_organizations.filter(is_default=True).count() == 1
    roles = set(Membership.all_organizations.filter(user__email="multi@example.com").values_list("role", flat=True))
    assert roles == {"admin", "reviewer"}


def test_the_seed_resets_the_institutes_sign_in_rules_and_domains(monkeypatch):
    """Whatever an earlier run or a person at the security page changed, sso.spec starts from the same place."""
    from apps.sso.models import VerifiedDomain
    from apps.tenancy.context import organization_context

    monkeypatch.setenv("HARAK_ALLOW_SEED", "1")
    call_command("seed_e2e")
    institute = Organization.objects.get(slug="sso")
    Organization.objects.filter(pk=institute.pk).update(mfa_required_for_managers=True, sso_session_hours=2)
    with organization_context(institute):
        VerifiedDomain.objects.create(
            domain="extra.test", token="t", created_by=User.objects.get(email="sso-admin@example.com")
        )
    call_command("seed_e2e")
    institute.refresh_from_db()
    assert (institute.mfa_required_for_managers, institute.sso_session_hours) == (False, 8)
    with organization_context(institute):
        assert list(VerifiedDomain.objects.values_list("domain", flat=True)) == ["vtc.test"]
