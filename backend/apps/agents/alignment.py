"""Alignment agent (spec 5.3): whether a link between an objective and a competency holds by meaning, and an
objective to suggest for a target competency no objective serves.

Rules already prove that links exist and that every target competency reaches an assessment; this agent
judges what rules cannot: meaning. It suggests only; a suggestion becomes content only when an author
writes it into the document.
"""

from dataclasses import dataclass

from apps.ai.gateway import AgentSpec, call
from apps.evals.evaluation import EvaluatedAgent, detection_score, register
from apps.quality.rules.harak1.bloom import classify_objective
from apps.quality.rules.harak1.objectives import check_objective

PROMPT_VERSION = "2026-10-03.1"

CHECK_INSTRUCTIONS = """You review the alignment between one learning objective of a vocational training programme and
one competency from the organisation's competency framework. Both are usually written in Arabic.

Answer "aligned" when achieving the objective clearly develops or demonstrates the competency, "weak" when
the objective only touches it (a related topic, a much lower level, or a small part of it), and
"misaligned" when the objective does not serve the competency. Judge meaning, not shared words. Give a
short explanation (one or two sentences) in the objective's language, and your confidence."""

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["aligned", "weak", "misaligned"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string", "maxLength": 600},
    },
    "required": ["verdict", "confidence", "explanation"],
    "additionalProperties": False,
}

SUGGEST_INSTRUCTIONS = """You draft one learning objective for a vocational training programme so that a competency it
targets, which no objective serves yet, is served. Write in the language of the competency (usually Arabic).

Write one behavioural objective: it starts with "أن" followed by one measurable present-tense verb, names
the trainee (المتدرب), states the content, and where natural a condition and a criterion. One outcome only;
no teacher activity, no topic-only phrasing, no unmeasurable verbs such as يفهم or يعرف. Give a short
explanation of how it serves the competency, and your confidence."""

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string", "minLength": 8, "maxLength": 400},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string", "maxLength": 600},
    },
    "required": ["objective", "confidence", "explanation"],
    "additionalProperties": False,
}

CHECK = AgentSpec(
    name="alignment",
    prompt_version=PROMPT_VERSION,
    instructions=CHECK_INSTRUCTIONS,
    schema=CHECK_SCHEMA,
    max_tokens=1500,
    effort="medium",
)
SUGGEST = AgentSpec(
    name="alignment_suggestion",
    prompt_version=PROMPT_VERSION,
    instructions=SUGGEST_INSTRUCTIONS,
    schema=SUGGEST_SCHEMA,
    max_tokens=1500,
    effort="medium",
)


@dataclass(frozen=True)
class Competency:
    code: str
    title: str
    description: str = ""

    def as_payload(self) -> dict:
        return {"code": self.code, "title": self.title, "description": self.description}


def check_payload(objective: str, competency: Competency) -> dict:
    return {"objective": objective, "competency": competency.as_payload()}


def suggest_payload(competency: Competency) -> dict:
    # The competency alone: a suggestion then stays valid (and cached) while the rest of the programme changes.
    return {"competency": competency.as_payload()}


def check(objective: str, competency: Competency, *, organization_id: int) -> tuple[dict, str]:
    result = call(CHECK, check_payload(objective, competency), organization_id=organization_id)
    return result.output, result.model


def suggest(competency: Competency, *, organization_id: int) -> tuple[dict, str]:
    result = call(SUGGEST, suggest_payload(competency), organization_id=organization_id)
    return result.output, result.model


def well_formed(objective: str) -> bool:
    """A suggestion is only shown if Harak's own rules accept it as a sound behavioural objective."""
    classified = classify_objective(objective)
    quality = check_objective(objective, classified)
    return (
        classified["domain"] is not None
        and not quality["errors"]
        and all(quality["components"][c] for c in ("an", "verb", "learner", "content"))
    )


def _competency(item: dict) -> Competency:
    return Competency(item["competency_code"], item["competency_title"], item.get("competency_description", ""))


register(
    EvaluatedAgent(
        spec=CHECK,
        input_fields=("objective", "competency_code", "competency_title", "competency_description"),
        labels=("aligned", "weak", "misaligned"),
        payload=lambda item: check_payload(item["objective"], _competency(item)),
        label_of=lambda output: output["verdict"],
        score=lambda gold, predicted: {
            **detection_score("misaligned")(gold, predicted),
            "accuracy": sum(g == p for g, p in zip(gold, predicted, strict=True)) / len(gold),
        },
    )
)

register(
    EvaluatedAgent(
        spec=SUGGEST,
        input_fields=("competency_code", "competency_title", "competency_description"),
        # Experts mark the competencies a sound objective can be written for; the score is the share of
        # suggestions Harak's rules accept. Meaning is judged by authors accepting or rejecting them in use.
        labels=("ok",),
        payload=lambda item: suggest_payload(_competency(item)),
        label_of=lambda output: "ok" if well_formed(output["objective"]) else "rejected",
        score=lambda gold, predicted: {
            "well_formed": sum(g == p for g, p in zip(gold, predicted, strict=True)) / len(gold)
        },
    )
)
