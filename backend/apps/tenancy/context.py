"""The single place that knows which organization the current request or task acts for.

A context variable is used instead of thread locals so the context follows
async code and stays isolated between threads and tasks.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_current_organization_id: ContextVar[int | None] = ContextVar("harak2_organization_id", default=None)


class OrganizationContextRequired(RuntimeError):
    """Raised when organization-scoped data is touched without an active organization."""


def _to_id(organization) -> int:
    return organization if isinstance(organization, int) else int(organization.pk)


def activate(organization) -> None:
    _current_organization_id.set(_to_id(organization))


def deactivate() -> None:
    _current_organization_id.set(None)


def has_context() -> bool:
    return _current_organization_id.get() is not None


def current_organization_id() -> int:
    organization_id = _current_organization_id.get()
    if organization_id is None:
        raise OrganizationContextRequired("no active organization: activate one before touching tenant data")
    return organization_id


@contextmanager
def organization_context(organization) -> Iterator[int]:
    token = _current_organization_id.set(_to_id(organization))
    try:
        yield _current_organization_id.get()  # type: ignore[misc]
    finally:
        _current_organization_id.reset(token)
