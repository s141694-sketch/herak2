"""The AI layer of a quality run (spec 5.2.3-5.2.4), through apps.ai.gateway only.

The classification agent reads objectives the rules could not settle (D42). Its readings are stored
on the objective analyses for the content they were made for, so unchanged blocks are never asked
again. Findings drawn from them are low-confidence suggestions; where the rule and the agent
disagree, both readings are shown.
"""

import hashlib
import json
from dataclasses import dataclass, field

from apps.ai.gateway import BY_DECISION, AIUnavailable

from .models import ObjectiveAnalysis

AI_SEVERITY = {
    "bloom_ai_level": "info",
    "bloom_disagreement": "info",
}


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


def has_current_reading(analysis: ObjectiveAnalysis) -> bool:
    return analysis.ai_status == "done" and analysis.ai_content_hash == analysis.content_hash


def needs_classification(analysis: ObjectiveAnalysis) -> bool:
    """The rules were not sure (D42) and the agent has not read this exact content yet."""
    return analysis.confidence != "high" and not has_current_reading(analysis)


def _reading(domain: str | None, level_id: int, level: str) -> dict:
    return {"domain": domain or None, "level_id": level_id, "level": level}


def findings_from(analyses) -> list[AIFinding]:
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
    return out


def classify(pending: list[ObjectiveAnalysis], *, organization_id: int) -> tuple[dict[int, dict], dict]:
    """Readings for the pending analyses (by primary key) and the state of the AI layer.

    A reason that is a decision (rules-only mode, agent not released, no provider) stops the layer and
    leaves the report complete; any other failure makes it partial (D38).
    """
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
    if reasons:
        return updates, {"status": "partial", "reasons": sorted(reasons)}
    return updates, {"status": "done", "reasons": []}


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
