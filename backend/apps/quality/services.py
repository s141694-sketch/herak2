"""Running the quality engine and acting on its findings (phase 4, task 4.3).

A run is requested with ``request_run``: the report gets a fresh run id and a background task does
the work. The task reads the version's rows, applies the rules, and replaces the report's rows in
one transaction, unless a newer run was requested meanwhile. Dismissals follow a finding's
fingerprint, within the version and from the version it was copied from.
"""

import uuid

import sentry_sdk
import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.competencies.models import Competency
from apps.programs.models import Node, ProgramVersion
from apps.programs.services import can_edit
from apps.tenancy.context import organization_context

from . import ai_layer
from .models import Finding, ObjectiveAnalysis, QualityReport, ReportLocked, Severity, engine_write
from .rules import program as program_rules
from .snapshot import load_snapshot

log = structlog.get_logger("harak2.quality")
S = QualityReport.Status
DRAFT = ProgramVersion.Status.DRAFT
MAX_REASON = 1000


class QualityError(ReportLocked):
    default_code = "quality_not_allowed"
    default_detail = "this action is not allowed on this report"


@transaction.atomic
def request_run(version: ProgramVersion, kind: str, *, actor=None, final: bool = False) -> QualityReport:
    """Ask for a run of ``kind`` (light or full). Only a draft's report is rerun, except the final run.

    ``final`` is the run started when the version leaves draft for review; a report that failed may also
    be run again after that.
    """
    version = ProgramVersion.objects.get(pk=version.pk)
    report = QualityReport.objects.select_for_update().filter(version=version).first()
    if version.status != DRAFT and not final and not (report and report.status == S.FAILED):
        raise QualityError("only a draft's report can be run again", code="report_locked")
    with engine_write():
        if report is None:
            report = QualityReport(version=version)
        report.run_id = uuid.uuid4()
        report.status = S.RUNNING
        report.last_run = kind
        report.requested_by = actor
        report.started_at = timezone.now()
        report.finished_at = None
        report.error = ""
        report.save()
    report_id, run_id = report.pk, str(report.run_id)

    def enqueue():
        from .tasks import run_report

        # The content change that asked for this run is already committed; a broker outage must not fail it.
        try:
            run_report.apply_async((report_id, run_id), retry=False)
        except Exception as exc:
            log.error("quality.enqueue_failed", report=report_id, error=str(exc))
            sentry_sdk.capture_exception(exc)

    transaction.on_commit(enqueue)
    return report


def execute_run(report_id: int, run_id: str) -> None:
    """The background work of one run: the rules now, then the AI layer. Does nothing if a newer run was requested.

    A full run (submission or a request) waits for the AI layer before the report is complete. A light run
    (after an edit) completes on the rules and leaves the AI layer to a later task, which only runs if no newer
    edit superseded it, so typing does not ask a model about every intermediate text.
    """
    report = QualityReport.all_organizations.select_related("version").get(pk=report_id)
    with organization_context(report.organization_id):
        if str(report.run_id) != run_id:
            return
        try:
            objectives, findings = program_rules.analyze(load_snapshot(report.version))
        except Exception as exc:  # the report must say it failed; the error goes to the technical alerts
            log.error("quality.run_failed", report=report_id, error=str(exc))
            sentry_sdk.capture_exception(exc)
            _finish(report_id, run_id, status=S.FAILED, error=str(exc)[:2000])
            return
        full = report.last_run == QualityReport.Run.FULL
        pending = _write_rules(report_id, run_id, objectives, findings, finish=not full)
        if pending is None:
            return
    if full:
        run_ai(report_id, run_id)
    elif pending:
        _schedule_ai(report_id, run_id)


def _schedule_ai(report_id: int, run_id: str) -> None:
    from .tasks import run_ai_layer

    try:
        run_ai_layer.apply_async((report_id, run_id), countdown=settings.QUALITY_AI_DELAY_SECONDS, retry=False)
    except Exception as exc:
        log.error("quality.enqueue_failed", report=report_id, error=str(exc))
        sentry_sdk.capture_exception(exc)


def run_ai(report_id: int, run_id: str) -> None:
    """The AI layer of a run. The calls happen outside any transaction; the results are written only if the run
    is still the latest (otherwise they stay in the gateway's cache for the next run)."""
    report = QualityReport.all_organizations.get(pk=report_id)
    with organization_context(report.organization_id):
        if str(report.run_id) != run_id:
            return
        pending = [a for a in report.objectives.all() if ai_layer.needs_classification(a)]
        updates, state = ai_layer.classify(pending, organization_id=report.organization_id)
        with transaction.atomic(), engine_write():
            report = QualityReport.objects.select_for_update().select_related("version").get(pk=report_id)
            if str(report.run_id) != run_id:
                return
            analyses = list(report.objectives.all())
            for analysis in analyses:
                for name, value in updates.get(analysis.pk, {}).items():
                    setattr(analysis, name, value)
            ObjectiveAnalysis.objects.bulk_update(analyses, ai_layer.AI_FIELDS)
            _replace_ai_findings(report, analyses, _carried_dismissals(report))
            report.ai_state = state
            if updates:
                from apps.agents import classification

                report.ai_prompts = {**report.ai_prompts, classification.NAME: classification.PROMPT_VERSION}
                models = sorted({a.ai_model for a in analyses if a.ai_model})
                if models:
                    report.ai_models = {**report.ai_models, classification.NAME: models[-1]}
            report.status = S.PARTIAL_RULES_ONLY if state["status"] == "partial" else S.COMPLETE
            report.finished_at = timezone.now()
            report.counts = counts(report.findings.all())
            report.save()


def _finish(report_id: int, run_id: str, *, status: str, error: str = "") -> None:
    with transaction.atomic(), engine_write():
        report = QualityReport.objects.select_for_update().get(pk=report_id)
        if str(report.run_id) != run_id:
            return
        report.status = status
        report.error = error
        report.finished_at = timezone.now()
        report.save()


def _carried_dismissals(report: QualityReport) -> dict[tuple[str, str], Finding]:
    """Dismissed findings this report already had, or, on its first run, those of the version it was copied from."""
    first_write = not report.rules_version
    if first_write and report.version.source_version_id:
        dismissed = Finding.objects.filter(
            report__version_id=report.version.source_version_id, dismissed_at__isnull=False
        )
    else:
        dismissed = Finding.objects.filter(report=report, dismissed_at__isnull=False)
    return {(f.source, f.fingerprint): f for f in dismissed}


def _finding_row(report, f, source, carried, competencies) -> Finding:
    previous = carried.get((source, f.fingerprint))
    return Finding(
        organization_id=report.organization_id,
        report=report,
        fingerprint=f.fingerprint,
        kind=f.kind,
        severity=f.severity,
        source=source,
        confidence=f.confidence,
        node_key=f.node_key,
        block_key=f.block_key,
        competency=competencies.get(f.competency_key),
        params=f.params,
        explanation=getattr(f, "explanation", ""),
        dismissed_reason=previous.dismissed_reason if previous else "",
        dismissed_by_id=previous.dismissed_by_id if previous else None,
        dismissed_at=previous.dismissed_at if previous else None,
    )


def _competencies(report, findings) -> dict:
    keys = {f.competency_key for f in findings if f.competency_key}
    return {
        str(c.competency_key): c
        for c in Competency.objects.filter(version=report.version.framework_version, competency_key__in=keys)
    }


def _replace_ai_findings(report, analyses, carried) -> None:
    Finding.objects.filter(report=report, source=Finding.Source.AI).delete()
    found = ai_layer.findings_from(analyses)
    competencies = _competencies(report, found)
    Finding.objects.bulk_create(_finding_row(report, f, Finding.Source.AI, carried, competencies) for f in found)


def _write_rules(report_id: int, run_id: str, objectives, findings, *, finish: bool) -> bool | None:
    """Replaces the report's rows with the rules' results, keeping the AI readings of unchanged objectives.

    Returns whether objectives still wait for the AI layer, or None when a newer run superseded this one.
    """
    with transaction.atomic(), engine_write():
        report = QualityReport.objects.select_for_update().select_related("version").get(pk=report_id)
        if str(report.run_id) != run_id:
            return None
        carried = _carried_dismissals(report)
        readings = {
            (str(a.block_key), a.ai_content_hash): {name: getattr(a, name) for name in ai_layer.AI_FIELDS}
            for a in ObjectiveAnalysis.objects.filter(report=report, ai_status="done")
        }
        Finding.objects.filter(report=report).delete()
        ObjectiveAnalysis.objects.filter(report=report).delete()
        analyses = ObjectiveAnalysis.objects.bulk_create(
            ObjectiveAnalysis(
                organization_id=report.organization_id,
                report=report,
                block_key=o.block_key,
                node_key=o.node_key,
                content_hash=o.content_hash,
                text=o.text,
                verb=o.verb,
                level_id=o.level_id,
                level=o.level,
                domain=o.domain or "",
                confidence=o.confidence,
                components=o.components,
                score=o.score,
                errors=o.errors,
                dimension=o.dimension,
                **readings.get((o.block_key, o.content_hash), {}),
            )
            for o in objectives
        )
        competencies = _competencies(report, findings)
        Finding.objects.bulk_create(
            _finding_row(report, f, Finding.Source.RULE, carried, competencies) for f in findings
        )
        _replace_ai_findings(report, analyses, carried)
        pending = any(ai_layer.needs_classification(a) for a in analyses)
        report.rules_version = program_rules.RULES_VERSION
        report.ai_state = {"status": "pending", "reasons": []} if pending else {"status": "done", "reasons": []}
        if finish:
            report.status = S.COMPLETE
            report.finished_at = timezone.now()
        report.counts = counts(report.findings.all())
        report.save()
        return pending


def counts(findings) -> dict[str, int]:
    """Open findings by severity; dismissed ones do not count."""
    totals = {severity: 0 for severity in Severity.values}
    for finding in findings:
        if finding.dismissed_at is None:
            totals[finding.severity] += 1
    return totals


def rollup(report: QualityReport) -> dict[str, dict[str, int]]:
    """Open findings of each node and everything under it, by severity, keyed by node key."""
    parents = {
        str(key): str(parent) if parent else None
        for key, parent in Node.objects.filter(version=report.version_id).values_list("node_key", "parent__node_key")
    }
    totals: dict[str, dict[str, int]] = {}
    for finding in report.findings.all():
        if finding.dismissed_at is not None or finding.node_key is None:
            continue
        key: str | None = str(finding.node_key)
        seen = set()
        while key is not None and key not in seen:
            seen.add(key)
            bucket = totals.setdefault(key, {severity: 0 for severity in Severity.values})
            bucket[finding.severity] += 1
            key = parents.get(key)
    return totals


def _editable_finding(finding: Finding, actor, role: str) -> Finding:
    finding = Finding.objects.select_related("report__version__program").get(pk=finding.pk)
    version = finding.report.version
    if version.status != DRAFT:
        raise QualityError("findings of a version that left draft cannot change", code="report_locked")
    if not can_edit(version.program, actor, role):
        raise QualityError("only the program's editors can dismiss findings", code="quality_not_allowed")
    return finding


@transaction.atomic
def dismiss(finding: Finding, *, reason: str, actor, role: str) -> Finding:
    finding = _editable_finding(finding, actor, role)
    reason = (reason or "").strip()
    if not reason:
        raise QualityError("a dismissal needs a reason", code="dismissal_reason_required")
    if len(reason) > MAX_REASON:
        raise QualityError(f"the reason is longer than {MAX_REASON} characters", code="dismissal_reason_too_long")
    finding.dismissed_reason = reason
    finding.dismissed_by = actor
    finding.dismissed_at = timezone.now()
    finding.save()
    _recount(finding.report)
    record(
        "quality.finding_dismissed",
        actor=actor,
        target=finding.report.version,
        payload={"finding": finding.pk, "kind": finding.kind, "fingerprint": finding.fingerprint, "reason": reason},
    )
    return finding


@transaction.atomic
def restore(finding: Finding, *, actor, role: str) -> Finding:
    finding = _editable_finding(finding, actor, role)
    finding.dismissed_reason = ""
    finding.dismissed_by = None
    finding.dismissed_at = None
    finding.save()
    _recount(finding.report)
    record(
        "quality.finding_restored",
        actor=actor,
        target=finding.report.version,
        payload={"finding": finding.pk, "kind": finding.kind, "fingerprint": finding.fingerprint},
    )
    return finding


def _recount(report: QualityReport) -> None:
    report = QualityReport.objects.select_for_update().get(pk=report.pk)
    report.counts = counts(report.findings.all())
    report.save(update_fields=["counts"])
