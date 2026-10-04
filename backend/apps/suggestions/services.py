"""Asking the drafting agent, keeping its answer if Harak's rules accept it, and recording the author's decision."""

import hashlib
import json
from datetime import timedelta

import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.agents import drafting, importing
from apps.agents.alignment import Competency
from apps.ai.gateway import AIUnavailable
from apps.audit.services import record
from apps.core.errors import Conflict
from apps.core.locking import VersionLocked
from apps.programs import lifecycle
from apps.programs.content import plain_text
from apps.programs.models import AlignmentLink, Block, ProgramVersion
from apps.quality.ai_layer import rules_only

from .models import Suggestion

log = structlog.get_logger("harak2.suggestions")


class SuggestionError(Conflict):
    default_code = "suggestion_error"


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _competency(item) -> Competency:
    return Competency(item.code, item.title, item.description or "")


def _rewrite_request(version: ProgramVersion, block_key) -> dict:
    block = Block.objects.filter(version=version, block_key=block_key, deleted=False).first() if block_key else None
    if block is None or block.type != Block.Type.OBJECTIVE:
        raise SuggestionError("a rewrite is for an objective of this version", code="suggestion_subject_invalid")
    text = plain_text(block.content).strip()
    if not drafting.needs_rewrite(text):
        raise SuggestionError("Harak's rules already accept this objective", code="objective_already_sound")
    links = AlignmentLink.objects.filter(
        version=version, source=block, kind=AlignmentLink.Kind.OBJECTIVE_COMPETENCY
    ).select_related("target_competency")
    competencies = [_competency(link.target_competency) for link in links.order_by("target_competency__order")]
    return drafting.rewrite_payload(text, competencies)


def _outline_request(version: ProgramVersion) -> dict:
    targets = [target.competency for target in version.targets.select_related("competency")]
    if not targets:
        raise SuggestionError("choose the competencies this version targets first", code="no_target_competencies")
    levels = _levels(version)
    program = version.program
    return drafting.outline_payload(program.title, program.target_role, levels, [_competency(c) for c in targets])


def request(version: ProgramVersion, kind: str, *, actor, block_key=None, text: str = "") -> Suggestion:
    """A suggestion for the version's current content; an open one for the same content is returned instead."""
    if not version.is_editable:
        raise VersionLocked()
    # The rows are read below; a live draft's latest content reaches them first when the editor can be reached.
    # This calls the collaboration service, so it happens before the transaction, not while holding it.
    lifecycle.rows_requested.send(sender=ProgramVersion, version=version)
    return _record_request(version, kind, actor=actor, block_key=block_key, text=text)


def _levels(version: ProgramVersion) -> list[str]:
    return [level.name_ar for level in version.program.template_version.levels.order_by("depth")]


def _import_request(version: ProgramVersion, text: str) -> dict:
    """The text as Harak 1 reads it, and the layout its rules give on this template, kept to fall back on."""
    try:
        read = importing.read(text)
    except importing.ImportTextInvalid as exc:
        code = "import_no_text" if exc.code == "NO_TEXT" else "import_text_invalid"
        raise SuggestionError(str(exc), code=code) from exc
    levels = _levels(version)
    return {"text": text, "levels": levels, "rules": importing.rules_proposal(read, level_count=len(levels))}


@transaction.atomic
def _record_request(version: ProgramVersion, kind: str, *, actor, block_key, text) -> Suggestion:
    if kind == Suggestion.Kind.REWRITE:
        payload, subject = _rewrite_request(version, block_key), str(block_key)
    elif kind == Suggestion.Kind.IMPORT:
        payload, subject = _import_request(version, text), ""
    else:
        payload, subject = _outline_request(version), ""
    basis = _hash(payload)
    existing = Suggestion.objects.filter(
        version=version, kind=kind, subject=subject, basis_hash=basis, status__in=Suggestion.OPEN
    ).first()
    if existing is not None and existing.status == Suggestion.Status.PENDING and _stale(existing):
        # Its worker was lost: it is closed as failed and a new request is made.
        Suggestion.objects.filter(pk=existing.pk, status=Suggestion.Status.PENDING).update(
            status=Suggestion.Status.FAILED, reason="unavailable", finished_at=timezone.now()
        )
        existing = None
    if existing is not None:
        return existing
    suggestion = Suggestion.objects.create(
        version=version, kind=kind, subject=subject, basis_hash=basis, request=payload, requested_by=actor
    )
    transaction.on_commit(lambda: _enqueue(suggestion))
    return suggestion


def _stale(suggestion: Suggestion) -> bool:
    return suggestion.created_at < timezone.now() - timedelta(minutes=settings.QUALITY_STALE_RUN_MINUTES)


def ai_hidden(suggestion: Suggestion) -> bool:
    """In rules-only mode no AI result is shown or applied, not even an earlier one (spec 5.1.4). An import's
    layout by Harak's rules stays usable."""
    if not rules_only(suggestion.organization_id):
        return False
    return suggestion.kind != Suggestion.Kind.IMPORT


def _enqueue(suggestion: Suggestion) -> None:
    from .tasks import run_suggestion

    try:
        run_suggestion.apply_async(args=[suggestion.pk], retry=False)
    except Exception as exc:  # noqa: BLE001 - the broker being down must not fail the author's request
        log.error("suggestions.enqueue_failed", suggestion=suggestion.pk, error=str(exc))
        Suggestion.objects.filter(pk=suggestion.pk, status=Suggestion.Status.PENDING).update(
            status=Suggestion.Status.FAILED, reason="unavailable", finished_at=timezone.now()
        )


def _import_answer(suggestion: Suggestion) -> tuple[str, str, dict, str]:
    """The agent's layout when it is usable; otherwise the rules' layout, with the reason the AI did not help.
    Either way the import is ready for the author to confirm or reject."""
    payload = suggestion.request
    rules = payload["rules"]
    read = importing.read(payload["text"])
    if len(read["lines"]) > importing.MAX_AI_LINES:
        return Suggestion.Status.READY, "too_long", rules, ""
    try:
        output, model = importing.distribute(read, payload["levels"], organization_id=suggestion.organization_id)
    except AIUnavailable as exc:
        return Suggestion.Status.READY, exc.reason, rules, ""
    try:
        shaped = importing.shape_import(output, lines=read["lines"], level_count=len(payload["levels"]))
    except importing.ImportRejected:
        return Suggestion.Status.READY, "ai_rejected", rules, model
    return (
        Suggestion.Status.READY,
        "",
        {**shaped, "confidence": output["confidence"], "explanation": output["explanation"]},
        model,
    )


def _answer(suggestion: Suggestion) -> tuple[str, str, dict, str]:
    """(status, reason, result, model) of asking the agent."""
    payload = suggestion.request
    organization_id = suggestion.organization_id
    if suggestion.kind == Suggestion.Kind.IMPORT:
        return _import_answer(suggestion)
    if suggestion.kind == Suggestion.Kind.REWRITE:
        output, model = drafting.rewrite(
            payload["objective"],
            [Competency(c["code"], c["title"], c.get("description", "")) for c in payload["competencies"]],
            organization_id=organization_id,
        )
        status, reason = drafting.judge_rewrite(payload["objective"], output)
        return status, reason or "", output, model
    output, model = drafting.outline(
        payload["programme"]["title"],
        payload["programme"]["target_role"],
        payload["levels"],
        [Competency(c["code"], c["title"], c.get("description", "")) for c in payload["competencies"]],
        organization_id=organization_id,
    )
    codes = {c["code"] for c in payload["competencies"]}
    try:
        shaped, dropped = drafting.shape_outline(output, level_count=len(payload["levels"]), competency_codes=codes)
    except drafting.OutlineRejected:
        return Suggestion.Status.REJECTED, "nothing_usable", output, model
    keys = {
        target.competency.code: str(target.competency.competency_key)
        for target in suggestion.version.targets.select_related("competency")
    }
    for objective in shaped["objectives"]:
        objective["competency_key"] = keys.get(objective["competency"])
    kept = [o for o in shaped["objectives"] if o["competency_key"]]
    # A competency may have left the targets since the request: its objectives go, and are counted as dropped.
    dropped["objectives"] += len(shaped["objectives"]) - len(kept)
    shaped["objectives"] = kept
    if not kept:
        return Suggestion.Status.REJECTED, "nothing_usable", output, model
    result = {
        **shaped,
        "dropped": dropped,
        "confidence": output["confidence"],
        "explanation": output["explanation"],
    }
    return Suggestion.Status.READY, "", result, model


def run(suggestion_id: int) -> None:
    """Asks the agent for a pending suggestion. A suggestion the author dismissed meanwhile stays dismissed."""
    suggestion = Suggestion.objects.select_related("version__program").filter(pk=suggestion_id).first()
    if suggestion is None or suggestion.status != Suggestion.Status.PENDING:
        return
    if not suggestion.version.is_editable:
        # The version left draft before a worker took the request: no model is asked for a locked version.
        Suggestion.objects.filter(pk=suggestion.pk, status=Suggestion.Status.PENDING).update(
            status=Suggestion.Status.FAILED, reason="version_locked", finished_at=timezone.now()
        )
        return
    spec = {
        Suggestion.Kind.REWRITE: drafting.REWRITE,
        Suggestion.Kind.OUTLINE: drafting.OUTLINE,
        Suggestion.Kind.IMPORT: importing.SPEC,
    }[suggestion.kind]
    try:
        status, reason, result, model = _answer(suggestion)
    except AIUnavailable as exc:
        status, reason, result, model = Suggestion.Status.FAILED, exc.reason, {}, ""
    with transaction.atomic():
        updated = Suggestion.objects.filter(pk=suggestion.pk, status=Suggestion.Status.PENDING).update(
            status=status,
            reason=reason[:50],
            result=result,
            model=model,
            prompt_version=spec.prompt_version,
            finished_at=timezone.now(),
        )
    if not updated:
        log.info("suggestions.answer_discarded", suggestion=suggestion.pk)


def _decide(suggestion: Suggestion, status: str, *, actor, reason: str = "", allowed=(Suggestion.Status.READY,)):
    with transaction.atomic():
        locked = Suggestion.objects.select_for_update().select_related("version").get(pk=suggestion.pk)
        if locked.status not in allowed:
            raise SuggestionError("this suggestion is no longer open", code="suggestion_not_open")
        # Rejecting changes nothing in the version, so it is recorded even after the version left draft.
        if status == Suggestion.Status.ACCEPTED and not locked.version.is_editable:
            raise VersionLocked()
        if status == Suggestion.Status.ACCEPTED and ai_hidden(locked):
            raise SuggestionError("the organization works with rules only", code="rules_only")
        locked.status = status
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.decision_reason = reason
        locked.save(update_fields=["status", "decided_by", "decided_at", "decision_reason"])
        record(
            f"ai_suggestion.{status}",
            actor=actor,
            target=locked.version,
            payload={"suggestion": locked.pk, "kind": locked.kind, "model": locked.model, "reason": reason},
        )
    return locked


def accept(suggestion: Suggestion, *, actor) -> Suggestion:
    """Recorded after the author's editor wrote the suggestion into the live document."""
    return _decide(suggestion, Suggestion.Status.ACCEPTED, actor=actor)


def dismiss(suggestion: Suggestion, *, actor, reason: str = "") -> Suggestion:
    return _decide(
        suggestion,
        Suggestion.Status.DISMISSED,
        actor=actor,
        reason=reason,
        allowed=(Suggestion.Status.PENDING, Suggestion.Status.READY),
    )
