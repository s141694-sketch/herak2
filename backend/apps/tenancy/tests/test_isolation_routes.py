"""Automatic isolation test (task 1.6): every API route, every tenant model."""

import importlib
import pkgutil

import pytest
from django.apps import apps as django_apps
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from rest_framework.test import APIClient

import apps as project_apps
from apps.accounts.models import Membership, Organization, Role, User
from apps.tenancy.context import organization_context
from apps.tenancy.isolation import EXEMPT_ROUTES, PROBES
from apps.tenancy.models import OrganizationScopedManager, OrganizationScopedModel

# Global tables that cannot carry a single organization (decision D10 in the decisions log).
# Tables without an organization, and why (decision D10, and D41 for the evaluation records).
GLOBAL_MODELS = {
    "accounts.User": "a user may belong to several organizations",
    "accounts.Organization": "the tenant itself",
    "evals.GoldenSet": "the golden set is the product's, built by the owner's experts (spec 8.2)",
    "evals.GoldenItem": "part of a golden set",
    "evals.AgentThreshold": "the owner's release thresholds apply to every organization (spec 5.5)",
    "evals.AgentEvaluation": "an agent version is released for all organizations or none",
}
PROJECT_APP_PREFIX = "apps."


def _load_probes() -> None:
    for module in pkgutil.walk_packages(project_apps.__path__, prefix="apps."):
        if module.name.endswith(".tests.isolation_probes"):
            importlib.import_module(module.name)


def _api_routes() -> dict[str, str]:
    """Every named route under /api/, as {name: pattern}."""
    found: dict[str, str] = {}

    def walk(patterns, prefix: str) -> None:
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                route = prefix + str(entry.pattern)
                if route.startswith("api/"):
                    if not entry.name:
                        raise AssertionError(f"API route {route} has no name; name it so isolation can track it")
                    found[entry.name] = route

    walk(get_resolver().url_patterns, "")
    return found


_load_probes()
ROUTES = _api_routes()


def test_every_api_route_is_exempt_or_probed():
    uncovered = sorted(name for name in ROUTES if name not in EXEMPT_ROUTES and name not in PROBES)
    assert not uncovered, (
        "routes without isolation coverage: "
        + ", ".join(f"{name} ({ROUTES[name]})" for name in uncovered)
        + ". Register a Probe in apps/<app>/tests/isolation_probes.py or, if the route touches no tenant data, "
        "add it to EXEMPT_ROUTES with a reason."
    )


def test_registry_has_no_stale_entries():
    stale = sorted((set(EXEMPT_ROUTES) | set(PROBES)) - set(ROUTES))
    assert not stale, f"isolation registry names routes that no longer exist: {stale}"


def test_every_project_table_carries_organization_id():
    offenders = []
    for model in django_apps.get_models():
        label = f"{model._meta.app_label}.{model.__name__}"
        if not model.__module__.startswith(PROJECT_APP_PREFIX) or ".tests." in model.__module__:
            continue
        if label in GLOBAL_MODELS:
            continue
        if not issubclass(model, OrganizationScopedModel):
            offenders.append(label)
        elif not isinstance(model._default_manager, OrganizationScopedManager):
            offenders.append(f"{label} (default manager is not organization-scoped)")
    assert not offenders, f"tables without organization scoping: {offenders}"


@pytest.fixture
def two_orgs(db):
    home = Organization.objects.create(name="Home", slug="home")
    other = Organization.objects.create(name="Other", slug="other")
    user = User.objects.create_user(email="isolation@example.com", password="x" * 12)
    with organization_context(home):
        Membership.objects.create(user=user, role=Role.ADMIN)
    client = APIClient()
    client.post("/api/auth/login/", {"email": "isolation@example.com", "password": "x" * 12}, format="json")
    return home, other, client


def _make(probe, org):
    with organization_context(org):
        return probe.make(org)


@pytest.mark.django_db
@pytest.mark.parametrize("route", sorted(name for name in PROBES))
def test_route_does_not_leak_other_organizations(route, two_orgs):
    home, other, client = two_orgs
    probe = PROBES[route]

    if probe.kind == "current":
        response = client.get(reverse(route))
        assert response.status_code == 200
        assert response.json()["id"] == home.pk
        return

    own = _make(probe, home)
    foreign = _make(probe, other)

    if probe.kind == "list":
        response = client.get(reverse(route))
        assert response.status_code == 200, response.content
        ids = probe.list_ids(response.json())
        assert own.pk in ids, "probe sanity: the caller's own object must be listed"
        assert foreign.pk not in ids, f"{route} lists an object of another organization"
        return

    own_url = reverse(route, kwargs=probe.url_kwargs(own))
    foreign_url = reverse(route, kwargs=probe.url_kwargs(foreign))

    if probe.kind == "action":
        for method in ("get", "post", "put", "patch", "delete"):
            status = getattr(client, method)(foreign_url, {}, format="json").status_code
            assert status in (403, 404, 405), f"{method.upper()} {route} on a foreign object returned {status}"
        return

    if probe.kind == "nested":
        assert client.get(own_url).status_code == 200, "probe sanity: the caller's own collection must be readable"
        assert client.get(foreign_url).status_code == 404, f"{route} exposes a collection of another organization"
        status = client.post(foreign_url, {}, format="json").status_code
        assert status in (403, 404, 405), f"POST {route} under a foreign parent returned {status}"
        return

    assert client.get(own_url).status_code == 200, "probe sanity: the caller's own object must be readable"
    assert client.get(foreign_url).status_code == 404, f"{route} exposes an object of another organization"
    for method in ("put", "patch", "delete"):
        status = getattr(client, method)(foreign_url, {}, format="json").status_code
        assert status in (403, 404, 405), f"{method.upper()} {route} on a foreign object returned {status}"
