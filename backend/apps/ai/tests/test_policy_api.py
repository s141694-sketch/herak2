import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.ai.models import AIPolicy, AIUsage
from apps.audit.models import AuditLog
from apps.programs.tests.factories import member
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


@pytest.fixture
def org(settings):
    settings.AI_MONTHLY_TOKEN_QUOTA = 5000
    organization = Organization.objects.create(name="A", slug="a")
    with organization_context(organization):
        member("admin@example.com", Role.ADMIN)
        member("author@example.com", Role.AUTHOR)
        AIUsage.objects.create(
            agent="x", prompt_version="v1", model="m", status="ok", input_tokens=40, output_tokens=2, cache_key="k"
        )
    return organization


def test_members_see_the_policy_and_this_months_use(org):
    body = login("author@example.com").get("/api/ai/policy/").json()
    assert body == {"id": org.pk, "mode": "ai", "monthly_token_quota": 5000, "used_this_month": 42}


def test_an_admin_switches_to_rules_only_and_it_is_audited(org):
    response = login("admin@example.com").put(
        "/api/ai/policy/", {"mode": "rules_only", "monthly_token_quota": 900}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["mode"] == "rules_only" and response.json()["monthly_token_quota"] == 900
    with organization_context(org):
        assert AIPolicy.objects.get().mode == "rules_only"
        assert AuditLog.objects.filter(event="ai.policy_changed").count() == 1


def test_only_admins_change_the_policy(org):
    assert login("author@example.com").put("/api/ai/policy/", {"mode": "rules_only"}, format="json").status_code == 403


def test_an_unknown_mode_is_refused(org):
    response = login("admin@example.com").put("/api/ai/policy/", {"mode": "sometimes"}, format="json")
    assert response.status_code == 400
