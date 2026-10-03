"""Lexical matching of objectives to standards or competencies by Jaccard similarity (Harak 1 section 6.4)."""

from . import data
from .jsre import js_round
from .text import jaccard, token_set


def score_confidence(score: float) -> str | None:
    thresholds = data.MATCH_THRESHOLDS
    if score > thresholds["high"]:
        return "high"
    if score >= thresholds["medium"]:
        return "medium"
    if score >= thresholds["low"]:
        return "low"
    return None


def round_score(score: float) -> float:
    return js_round(score * 100) / 100


def match_standards(objectives: list[str], standards: list[dict]) -> list[dict]:
    """Every (objective, standard) pair at or above the low threshold, best first; ties keep input order.

    ``standards`` are ``{"id", "code", "text"}``; the compared text is the code followed by the text, as in Harak 1.
    """
    pool = [
        {
            "id": s.get("id") or s.get("code"),
            "text": " ".join(part for part in (s.get("code"), s.get("text")) if part),
        }
        for s in standards
    ]
    for s in pool:
        s["tokens"] = token_set(s["text"])
    out = []
    for index, objective in enumerate(objectives):
        tokens = token_set(objective)
        for s in pool:
            score = jaccard(tokens, s["tokens"])
            confidence = score_confidence(score)
            if not confidence:
                continue
            out.append(
                {
                    "objective": index,
                    "standardId": s["id"],
                    "standardText": s["text"],
                    "score": round_score(score),
                    "confidence": confidence,
                }
            )
    return sorted(out, key=lambda m: -m["score"])
