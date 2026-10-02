"""Registry for the automatic cross-organization isolation test (task 1.6).

Every route under /api/ must be either declared here as not touching tenant
data (with a reason), or covered by a probe that creates an object in another
organization and proves it cannot be read or changed. The test in
apps/tenancy/tests/test_isolation_routes.py fails on any route that is neither.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# Route names that never touch tenant data, with the reason they are exempt.
EXEMPT_ROUTES: dict[str, str] = {
    "health": "public liveness probe; reads no tenant data",
    "auth-csrf": "sets the CSRF cookie only",
    "auth-login": "authenticates a user; memberships listed are the user's own",
    "auth-logout": "ends the caller's session",
    "auth-me": "returns the caller and the caller's own memberships",
    "auth-switch-organization": "membership-checked switch; covered by test_auth_api",
}

ProbeKind = Literal["detail", "list", "current"]


@dataclass(frozen=True)
class Probe:
    """How to prove one route isolates organizations.

    detail:  `make(org)` returns an object; `url_kwargs(obj)` builds the route kwargs.
             Reading or changing another organization's object must fail.
    list:    `make(org)` returns an object; its `id` must not appear in another organization's list.
    current: the route describes the active organization itself; it must name the caller's organization.
    """

    route: str
    kind: ProbeKind
    make: Callable[[Any], Any] | None = None
    url_kwargs: Callable[[Any], dict] = field(default=lambda obj: {"pk": obj.pk})
    # Extracts the ids from a list response.
    list_ids: Callable[[Any], list] = field(default=lambda body: [item["id"] for item in body])


PROBES: dict[str, Probe] = {}


def register(probe: Probe) -> Probe:
    if probe.route in PROBES:
        raise ValueError(f"probe for {probe.route} registered twice")
    PROBES[probe.route] = probe
    return probe
