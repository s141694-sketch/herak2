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
    "auth-password-forgot": "queues an email to the address given; answers the same whether it has an account",
    "auth-password-set": (
        "sets the password of the person a signed, single-use link names; reads only that person's own memberships, "
        "to audit the change in each of their organizations"
    ),
    "auth-logout": "ends the caller's session",
    "auth-me": "returns the caller and the caller's own memberships",
    "file-content": (
        "serves the one file a signed, expiring link names; file-download signs it after checking the caller's "
        "organization and access (D98); covered by test_local_store"
    ),
    "auth-invitation-answer": (
        "the caller answers their own invitation, found by its id and the caller together (D90); covered by "
        "test_invitations"
    ),
    "auth-mfa-verify": "before sign-in; the caller's own second factor, a person-wide table (D70)",
    "auth-mfa-enrol": "the caller's own second factor, a person-wide table (D70)",
    "auth-mfa-confirm": "the caller's own second factor; returns the caller's own memberships",
    "auth-mfa-disable": "the caller's own second factor, a person-wide table (D70)",
    "auth-sso-start": "before sign-in; the organization comes from the email's verified domain, nothing is returned",
    "organization-identity": "describes the active organization only, as organization-current does; no object id",
    "organization-identity-logo": "changes the active organization only; its logo is reached by file-download",
    "auth-sso-discover": "before sign-in; says only whether the email's domain has a provider, nothing is written",
    "auth-sso-callback": "before sign-in; the organization comes from the provider of the flow this session began",
    "auth-switch-organization": "membership-checked switch; covered by test_auth_api",
    "internal-collab-document": "collab service only (service secret); organization taken from the version",
    "internal-collab-document-failure": "collab service only (service secret); organization taken from the version",
}

ProbeKind = Literal["detail", "list", "nested", "action", "current"]


@dataclass(frozen=True)
class Probe:
    """How to prove one route isolates organizations.

    detail:  `make(org)` returns an object; `url_kwargs(obj)` builds the route kwargs.
             Reading or changing another organization's object must fail.
    list:    `make(org)` returns an object; its `id` must not appear in another organization's list.
    nested:  a collection under a parent object built by `make(org)`; a foreign parent gives 404 on GET and
             the POST that would add to it is refused.
    action:  a POST-only action on an object built by `make(org)`; a foreign object is refused.
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
