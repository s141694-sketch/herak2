"""The AI layer of a quality run (spec 5.2.3-5.2.4), through apps.ai.gateway only.

Three cases, as the spec lists them: an objective the rules could not classify with confidence (D42), the
meaning of an existing objective-competency link, and a target competency no objective serves (a suggested
objective). Every judgement is kept for the inputs it was made for, so unchanged content is never sent
again; findings drawn from them are suggestions, shown with the agent's explanation.
"""

import hashlib
import json
from dataclasses import dataclass, field

from apps.ai.gateway import BY_DECISION, AIUnavailable
from apps.competencies.models import Competency
from apps.programs.models import AlignmentLink

from .models import AICheck, Finding, ObjectiveAnalysis

AI_SEVERITY = {
    "bloom_ai_level": "info",
    "bloom_disagreement": "info",
    "link_semantic_mismatch": "warning",
    "link_semantic_weak": "info",
    "competency_objective_suggestion": "info",
}

AI_FIELDS = (
    "ai_status",
    "ai_content_hash",
    "ai_domain",
    "ai_level_id",
    "ai_level",
    "ai_verb",
    "ai_confidence",
    "ai_explanation",
    "ai_model",
)


@dataclass(frozen=True)
class AIFinding:
    kind: str
    node_key: str | None
    block_key: str | None = None
    competency_key: str | None = None
    confidence: str = "low"
    params: dict = field(default_factory=dict)
    explanation: str = ""

    @property
    def severity(self) -> str:
        return AI_SEVERITY[self.kind]

    @property
    def fingerprint(self) -> str:
        identity = json.dumps([self.kind, self.node_key, self.block_key, self.competency_key])
        return hashlib.sha256(identity.encode()).hexdigest()


@dataclass(frozen=True)
class Subject:
    """Something the alignment agent is asked about, with the inputs that decide whether an answer still holds."""

    kind: str
    subject: str
    basis_hash: str
    competency: dict
    node_key: str | None
    competency_key: str
    block_key: str | None = None
    objective: str = ""


def rules_only(organization_id: int) -> bool:
    """An organization in rules-only mode sees no AI results at all, not even earlier ones (spec 5.1.4)."""
    from apps.ai.models import AIPolicy

    return AIPolicy.objects.filter(organization_id=organization_id, mode=AIPolicy.Mode.RULES_ONLY).exists()


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _competency_payload(c: Competency) -> dict:
    return {"code": c.code, "title": c.title, "description": c.description}


# ---- classification of objectives -----------------------------------------------------------------------


def has_current_reading(analysis: ObjectiveAnalysis) -> bool:
    return analysis.ai_status == "done" and analysis.ai_content_hash == analysis.content_hash


def needs_classification(analysis: ObjectiveAnalysis) -> bool:
    """The rules were not sure (D42) and the agent has not read this exact content yet."""
    return analysis.confidence != "high" and not has_current_reading(analysis)


def _reading(domain: str | None, level_id: int, level: str) -> dict:
    return {"domain": domain or None, "level_id": level_id, "level": level}


def classify(pending: list[ObjectiveAnalysis], *, organization_id: int) -> tuple[dict[int, dict], dict]:
    """Readings for the pending analyses (by primary key) and the state of this part of the layer."""
    from apps.agents import classification

    updates: dict[int, dict] = {}
    reasons: set[str] = set()
    for analysis in pending:
        try:
            reading = classification.classify(analysis.text, organization_id=organization_id)
        except AIUnavailable as exc:
            if exc.reason in BY_DECISION:
                return updates, {"status": "skipped", "reasons": [exc.reason]}
            reasons.add(exc.reason)
            updates[analysis.pk] = {"ai_status": "failed", "ai_content_hash": analysis.content_hash}
            if exc.reason == "quota_exceeded":
                break
            continue
        except classification.ImplausibleAnswer:
            reasons.add("invalid_output")
            updates[analysis.pk] = {"ai_status": "failed", "ai_content_hash": analysis.content_hash}
            continue
        updates[analysis.pk] = {
            "ai_status": "done",
            "ai_content_hash": analysis.content_hash,
            "ai_domain": reading.domain or "",
            "ai_level_id": reading.level_id,
            "ai_level": reading.level,
            "ai_verb": reading.verb,
            "ai_confidence": reading.confidence,
            "ai_explanation": reading.explanation,
            "ai_model": reading.model,
        }
    return updates, (
        {"status": "partial", "reasons": sorted(reasons)} if reasons else {"status": "done", "reasons": []}
    )


# ---- alignment ---------------------------------------------------------------------------------------------


def alignment_subjects(report) -> dict[tuple[str, str], Subject]:
    """Links from live objectives to competencies, and target competencies no objective serves."""
    analyses = {str(a.block_key): a for a in report.objectives.all()}
    subjects: dict[tuple[str, str], Subject] = {}
    links = AlignmentLink.objects.filter(version=report.version_id, kind="objective_competency").select_related(
        "source", "target_competency"
    )
    for link in links:
        analysis = analyses.get(str(link.source.block_key))
        if analysis is None or link.target_competency is None:
            continue
        competency = _competency_payload(link.target_competency)
        key = str(link.target_competency.competency_key)
        subject = f"{analysis.block_key}:{key}"
        subjects[("link", subject)] = Subject(
            "link",
            subject,
            _hash([analysis.text, competency]),
            competency,
            str(analysis.node_key),
            key,
            block_key=str(analysis.block_key),
            objective=analysis.text,
        )
    uncovered = report.findings.filter(source=Finding.Source.RULE, kind="competency_not_assessed").select_related(
        "competency"
    )
    for finding in uncovered:
        if finding.params.get("has_objective") or finding.competency is None:
            continue
        competency = _competency_payload(finding.competency)
        key = str(finding.competency.competency_key)
        subjects[("suggestion", key)] = Subject(
            "suggestion", key, _hash([competency]), competency, str(finding.node_key) if finding.node_key else None, key
        )
    return subjects


def current_checks(report, subjects: dict[tuple[str, str], Subject]) -> list[AICheck]:
    return [
        check
        for check in report.checks.all()
        if (check.kind, check.subject) in subjects
        and subjects[(check.kind, check.subject)].basis_hash == check.basis_hash
    ]


def needs_judgement(report, subjects: dict[tuple[str, str], Subject]) -> list[Subject]:
    answered = {(c.kind, c.subject) for c in current_checks(report, subjects) if c.status in ("done", "rejected")}
    return [s for key, s in subjects.items() if key not in answered]


def judge(todo: list[Subject], *, organization_id: int) -> tuple[list[dict], dict]:
    """Asks the alignment agent about each subject; returns the checks to store and the state of this part."""
    from apps.agents import alignment

    results: list[dict] = []
    reasons: set[str] = set()
    skipped: dict[str, str] = {}
    for subject in todo:
        spec = alignment.CHECK if subject.kind == "link" else alignment.SUGGEST
        if spec.name in skipped or "quota_exceeded" in reasons:
            continue
        competency = alignment.Competency(**subject.competency)
        row = {"kind": subject.kind, "subject": subject.subject, "basis_hash": subject.basis_hash}
        try:
            if subject.kind == "link":
                output, model = alignment.check(subject.objective, competency, organization_id=organization_id)
                status = "done"
            else:
                output, model = alignment.suggest(competency, organization_id=organization_id)
                status = "done" if alignment.well_formed(output["objective"]) else "rejected"
        except AIUnavailable as exc:
            if exc.reason in BY_DECISION:
                skipped[spec.name] = exc.reason
                continue
            reasons.add(exc.reason)
            results.append({**row, "status": "failed", "result": {}, "model": ""})
            continue
        results.append({**row, "status": status, "result": output, "model": model})
    if reasons:
        return results, {"status": "partial", "reasons": sorted(reasons)}
    if skipped and len(skipped) == len({s.kind for s in todo}):
        return results, {"status": "skipped", "reasons": sorted(set(skipped.values()))}
    return results, {"status": "done", "reasons": []}


def combine(*states: dict) -> dict:
    """One state for the layer: partial if any part failed, skipped if every part was skipped by decision."""
    if any(s["status"] == "partial" for s in states):
        return {
            "status": "partial",
            "reasons": sorted({r for s in states if s["status"] == "partial" for r in s["reasons"]}),
        }
    skipped = [s for s in states if s["status"] == "skipped"]
    if skipped and len(skipped) == len(states):
        return {"status": "skipped", "reasons": sorted({r for s in skipped for r in s["reasons"]})}
    return {"status": "done", "reasons": []}


# ---- findings ----------------------------------------------------------------------------------------------


def findings_from(analyses, checks=(), subjects=None) -> list[AIFinding]:
    out = []
    for a in analyses:
        if not has_current_reading(a) or not a.ai_domain:
            continue
        ai = {**_reading(a.ai_domain, a.ai_level_id or 0, a.ai_level), "verb": a.ai_verb}
        key, node = str(a.block_key), str(a.node_key)
        if not a.domain:
            out.append(AIFinding("bloom_ai_level", node, key, params={"ai": ai}, explanation=a.ai_explanation))
        elif (a.ai_domain, a.ai_level_id) != (a.domain, a.level_id):
            rule = _reading(a.domain, a.level_id, a.level)
            out.append(
                AIFinding(
                    "bloom_disagreement", node, key, params={"rule": rule, "ai": ai}, explanation=a.ai_explanation
                )
            )
    for check in checks:
        if check.status != "done":
            continue
        subject = (subjects or {}).get((check.kind, check.subject))
        if subject is None:
            continue
        result = check.result
        if check.kind == "link" and result.get("verdict") in ("misaligned", "weak"):
            kind = "link_semantic_mismatch" if result["verdict"] == "misaligned" else "link_semantic_weak"
            out.append(
                AIFinding(
                    kind,
                    subject.node_key,
                    subject.block_key,
                    subject.competency_key,
                    confidence=result["confidence"],
                    explanation=result["explanation"],
                )
            )
        elif check.kind == "suggestion":
            out.append(
                AIFinding(
                    "competency_objective_suggestion",
                    subject.node_key,
                    None,
                    subject.competency_key,
                    confidence=result["confidence"],
                    params={"objective": result["objective"]},
                    explanation=result["explanation"],
                )
            )
    return out
