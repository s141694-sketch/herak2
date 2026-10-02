"""Phase 1 completion criterion: two users in two organizations sign in and neither sees the other's data."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Organization, Role, User
from apps.audit.services import record
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


def test_two_organizations_see_nothing_of_each_other():
    worlds = {}
    for slug in ("east", "west"):
        org = Organization.objects.create(name=slug, slug=slug)
        user = User.objects.create_user(email=f"{slug}@example.com", password="x" * 12)
        with organization_context(org):
            Membership.objects.create(user=user, role=Role.ADMIN)
            colleague = User.objects.create_user(email=f"colleague-{slug}@example.com", password="x" * 12)
            Membership.objects.create(user=colleague, role=Role.AUTHOR)
            record(f"{slug}.created", actor=user)
        client = APIClient()
        response = client.post("/api/auth/login/", {"email": user.email, "password": "x" * 12}, format="json")
        assert response.status_code == 200
        worlds[slug] = (org, client)

    for slug, (_org, client) in worlds.items():
        other_slug = "west" if slug == "east" else "east"
        other_org, _ = worlds[other_slug]

        assert client.get("/api/organizations/current/").json()["slug"] == slug
        members = client.get("/api/organizations/current/members/").json()
        emails = {m["user"]["email"] for m in members}
        assert emails == {f"{slug}@example.com", f"colleague-{slug}@example.com"}
        assert not any(other_slug in email for email in emails)

        with organization_context(other_org):
            foreign_ids = list(Membership.objects.values_list("pk", flat=True))
        for pk in foreign_ids:
            assert client.get(f"/api/organizations/current/members/{pk}/").status_code == 404

        switch = client.post("/api/auth/switch-organization/", {"organization_id": other_org.pk}, format="json")
        assert switch.status_code == 404
