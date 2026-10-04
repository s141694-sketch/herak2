"""The single write point of the audit log."""

import structlog
from django.db import models
from django.dispatch import Signal

from .models import AuditLog, _write_allowed

# Sent after an entry is written, inside the writer's transaction. The automations (spec 6.4) start here:
# every event is written to the audit log first, and what follows is derived from the entry.
recorded = Signal()


def record(event: str, *, actor=None, target: models.Model | None = None, payload: dict | None = None) -> AuditLog:
    """Appends one entry to the active organization's audit log and returns it."""
    request_id = structlog.contextvars.get_contextvars().get("request_id", "")
    entry = AuditLog(
        event=event,
        actor=actor,
        actor_email=getattr(actor, "email", "") or "",
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        payload=payload or {},
        request_id=request_id,
    )
    token = _write_allowed.set(True)
    try:
        entry.save()
    finally:
        _write_allowed.reset(token)
    recorded.send(sender=AuditLog, entry=entry)
    return entry
