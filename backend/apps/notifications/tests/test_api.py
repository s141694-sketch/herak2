"""The notifications API (task 5.8): one's own notifications, unread count, marking read, and the email choice."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.notifications.models import Notification
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        me = member("me@example.com", Role.REVIEWER)
        other = member("other@example.com", Role.REVIEWER)
        for user in (me, other):
            user.set_password("x" * 12)
            user.save()
        version = program(member("author@example.com", Role.AUTHOR)).versions.get()
        mine = [
            Notification.objects.create(recipient=me, event="task_assigned", version=version, audit_entry=i)
            for i in (1, 2)
        ]
        Notification.objects.create(recipient=other, event="task_assigned", version=version, audit_entry=1)
    return {"mine": mine}


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


def test_a_member_sees_and_reads_only_their_notifications(world):
    me = login("me@example.com")
    body = me.get("/api/notifications/").json()
    assert sorted(n["id"] for n in body["items"]) == sorted(n.pk for n in world["mine"])
    assert body["unread"] == 2 and body["email"] == "immediate"
    first = world["mine"][0].pk
    assert me.post(f"/api/notifications/{first}/read/").json()["read_at"] is not None
    assert me.get("/api/notifications/").json()["unread"] == 1
    assert me.post("/api/notifications/", {"read_all": True}, format="json").json()["unread"] == 0
    assert login("other@example.com").post(f"/api/notifications/{first}/read/").status_code == 404
    assert login("other@example.com").get("/api/notifications/").json()["unread"] == 1


def test_a_member_chooses_how_email_follows(world):
    me = login("me@example.com")
    assert me.post("/api/notifications/", {"email": "daily"}, format="json").json()["email"] == "daily"
    assert me.get("/api/notifications/").json()["email"] == "daily"
    assert me.post("/api/notifications/", {"email": "never"}, format="json").status_code == 400
