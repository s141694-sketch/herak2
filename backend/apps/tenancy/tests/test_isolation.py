import threading

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.accounts.models import Membership, Organization, Role, User
from apps.tenancy.context import (
    OrganizationContextRequired,
    activate,
    current_organization_id,
    deactivate,
    has_context,
    organization_context,
)
from apps.tenancy.middleware import OrganizationContextMiddleware
from apps.tenancy.models import CrossOrganizationError

from .testapp.models import Part, Widget

pytestmark = pytest.mark.django_db


@pytest.fixture
def orgs():
    a = Organization.objects.create(name="A", slug="a")
    b = Organization.objects.create(name="B", slug="b")
    with organization_context(a):
        Widget.objects.create(name="a-1")
        Widget.objects.create(name="a-2")
    with organization_context(b):
        Widget.objects.create(name="b-1")
    return a, b


@pytest.fixture(autouse=True)
def clean_context():
    deactivate()
    yield
    deactivate()


def test_query_without_organization_context_is_rejected(orgs):
    with pytest.raises(OrganizationContextRequired):
        list(Widget.objects.all())
    with pytest.raises(OrganizationContextRequired):
        Widget.objects.count()
    with pytest.raises(OrganizationContextRequired):
        Widget.objects.filter(name="a-1").exists()


def test_queries_see_only_the_active_organization(orgs):
    a, b = orgs
    with organization_context(a):
        assert sorted(Widget.objects.values_list("name", flat=True)) == ["a-1", "a-2"]
    with organization_context(b):
        assert list(Widget.objects.values_list("name", flat=True)) == ["b-1"]
        with pytest.raises(Widget.DoesNotExist):
            Widget.objects.get(name="a-1")


def test_other_organizations_rows_are_invisible_even_by_primary_key(orgs):
    a, b = orgs
    with organization_context(a):
        pk = Widget.objects.get(name="a-1").pk
    with organization_context(b):
        assert not Widget.objects.filter(pk=pk).exists()
        with pytest.raises(Widget.DoesNotExist):
            Widget.objects.get(pk=pk)


def test_save_assigns_the_active_organization(orgs):
    a, _ = orgs
    with organization_context(a):
        widget = Widget.objects.create(name="new")
        assert widget.organization_id == a.pk
        widget = Widget(name="also-new")
        widget.save()
        assert widget.organization_id == a.pk


def test_save_rejects_a_foreign_organization(orgs):
    a, b = orgs
    with organization_context(a):
        with pytest.raises(CrossOrganizationError):
            Widget.objects.create(name="x", organization=b)
        with pytest.raises(CrossOrganizationError):
            Widget(name="x", organization_id=b.pk).save()
    with pytest.raises(OrganizationContextRequired):
        Widget(name="x", organization=a).save()


def test_related_objects_must_belong_to_the_same_organization(orgs):
    a, b = orgs
    with organization_context(b):
        foreign = Widget.objects.get(name="b-1")
    with organization_context(a):
        own = Widget.objects.get(name="a-1")
        Part.objects.create(widget=own, name="ok")
        with pytest.raises(CrossOrganizationError):
            Part.objects.create(widget=foreign, name="leak")


def test_explicit_unscoped_manager_is_the_only_way_across_organizations(orgs):
    assert Widget.all_organizations.count() == 3
    assert Widget._default_manager is Widget.objects


def test_membership_is_organization_scoped(orgs):
    a, b = orgs
    user = User.objects.create_user(email="u@example.com", password="x" * 12)
    # Writes always happen inside a context; the unscoped manager is for cross-organization reads.
    with organization_context(a):
        Membership.objects.create(user=user, role=Role.AUTHOR)
    with organization_context(b):
        Membership.objects.create(user=user, role=Role.REVIEWER)
    with pytest.raises(OrganizationContextRequired):
        Membership.all_organizations.create(user=user, organization=a, role=Role.ADMIN)
    with pytest.raises(OrganizationContextRequired):
        list(user.memberships.all())
    with organization_context(a):
        assert [m.role for m in Membership.objects.filter(user=user)] == ["author"]
    assert Membership.all_organizations.filter(user=user).count() == 2


def test_context_is_per_thread(orgs):
    a, b = orgs
    seen: dict[str, object] = {}

    def worker():
        seen["before"] = has_context()
        with organization_context(b):
            seen["inside"] = current_organization_id()
        seen["after"] = has_context()

    with organization_context(a):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert current_organization_id() == a.pk
    assert seen == {"before": False, "inside": b.pk, "after": False}


def test_activate_accepts_an_organization_or_its_id(orgs):
    a, _ = orgs
    activate(a)
    assert current_organization_id() == a.pk
    deactivate()
    activate(a.pk)
    assert current_organization_id() == a.pk


class TestMiddleware:
    @pytest.fixture
    def user(self, orgs):
        a, b = orgs
        user = User.objects.create_user(email="u@example.com", password="x" * 12)
        with organization_context(a):
            Membership.objects.create(user=user, role=Role.AUTHOR)
        return user

    def run(self, user, session: dict):
        captured: dict[str, object] = {}

        def view(request):
            captured["organization"] = request.organization
            captured["context"] = current_organization_id() if has_context() else None
            return HttpResponse()

        request = RequestFactory().get("/api/anything/")
        request.user = user
        request.session = session
        response = OrganizationContextMiddleware(view)(request)
        assert response.status_code == 200
        return captured, session

    def test_session_organization_becomes_the_request_context(self, user, orgs):
        a, _ = orgs
        captured, _ = self.run(user, {"organization_id": a.pk})
        assert captured["organization"] == a
        assert captured["context"] == a.pk
        assert not has_context(), "context must be cleared after the request"

    def test_single_membership_is_selected_automatically(self, user, orgs):
        a, _ = orgs
        captured, session = self.run(user, {})
        assert captured["organization"] == a
        assert session["organization_id"] == a.pk

    def test_non_member_organization_in_session_is_dropped(self, user, orgs):
        a, b = orgs
        captured, session = self.run(user, {"organization_id": b.pk})
        # The stale value is replaced by the only organization the user belongs to.
        assert captured["organization"] == a
        assert session["organization_id"] == a.pk

    def test_user_with_several_memberships_and_no_choice_has_no_context(self, user, orgs):
        _, b = orgs
        with organization_context(b):
            Membership.objects.create(user=user, role=Role.REVIEWER)
        captured, session = self.run(user, {"organization_id": 999})
        assert captured == {"organization": None, "context": None}
        assert "organization_id" not in session

    def test_anonymous_request_has_no_context(self, orgs):
        from django.contrib.auth.models import AnonymousUser

        captured, _ = self.run(AnonymousUser(), {})
        assert captured == {"organization": None, "context": None}
