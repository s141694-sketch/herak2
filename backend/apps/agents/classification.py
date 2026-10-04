"""Classification agent (spec 5.3): the Bloom level of objectives the rules could not settle.

It runs on objectives whose rule confidence is not high (no clear verb, a verb unknown to the
dictionary, or a verb that sits on several levels, D42). Its answer is shown next to the rule's,
and a disagreement is shown explicitly with low confidence (spec 5.2.4).
"""

from dataclasses import dataclass

from apps.ai.gateway import AgentSpec, AIResult, call
from apps.evals.evaluation import EvaluatedAgent, classification_score, register
from apps.quality.rules.harak1 import data

NAME = "classification"
PROMPT_VERSION = "2026-10-03.1"

LEVELS = {
    "cognitive": {level["id"]: level["name"] for level in data.BLOOM_LEVELS},
    "affective": {level["id"]: level["name"] for level in data.RAW["affective"]["levels"]},
    "psychomotor": {level["id"]: level["name"] for level in data.RAW["psychomotor"]["levels"]},
}


def _levels_text() -> str:
    lines = []
    for domain, levels in LEVELS.items():
        lines.append(f"- {domain}: " + ", ".join(f"{i} = {name}" for i, name in levels.items()))
    return "\n".join(lines)


INSTRUCTIONS = f"""You classify one learning objective from a vocational training programme, usually written in
Arabic, into a taxonomy of learning outcomes.

Domains and level ids:
{_levels_text()}

Decide which domain the objective's main observable behaviour belongs to and its level in that domain.
Judge the behaviour the trainee must show, not the topic. When the objective has no observable
behaviour, or you cannot decide, answer domain "unclear" with level_id 0. Report the verb you based the
decision on, exactly as written. Give a short explanation (one or two sentences) in the objective's
language, and your confidence."""

SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "enum": ["cognitive", "affective", "psychomotor", "unclear"]},
        "level_id": {"type": "integer", "minimum": 0, "maximum": 7},
        "verb": {"type": "string", "maxLength": 60},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string", "maxLength": 600},
    },
    "required": ["domain", "level_id", "verb", "confidence", "explanation"],
    "additionalProperties": False,
}

SPEC = AgentSpec(
    name=NAME, prompt_version=PROMPT_VERSION, instructions=INSTRUCTIONS, schema=SCHEMA, max_tokens=2000, effort="medium"
)


@dataclass(frozen=True)
class Classification:
    domain: str | None
    level_id: int
    level: str
    verb: str
    confidence: str
    explanation: str
    model: str


class ImplausibleAnswer(ValueError):
    """Valid JSON whose meaning does not hold (a level outside its domain); never shown."""


def interpret(output: dict, model: str = "") -> Classification:
    domain = output["domain"]
    if domain == "unclear":
        if output["level_id"] != 0:
            raise ImplausibleAnswer("an unclear objective has level 0")
        return Classification(None, 0, "", output["verb"], output["confidence"], output["explanation"], model)
    levels = LEVELS[domain]
    if output["level_id"] not in levels:
        raise ImplausibleAnswer(f"{domain} has no level {output['level_id']}")
    return Classification(
        domain,
        output["level_id"],
        levels[output["level_id"]],
        output["verb"],
        output["confidence"],
        output["explanation"],
        model,
    )


def classify(text: str, *, organization_id: int) -> Classification:
    result: AIResult = call(SPEC, payload(text), organization_id=organization_id, accept=plausible)
    return interpret(result.output, result.model)


def plausible(output: dict) -> bool:
    try:
        interpret(output)
    except ImplausibleAnswer:
        return False
    return True


def payload(text: str) -> dict:
    return {"objective": text}


def label_of(output: dict) -> str:
    return "unclear" if output["domain"] == "unclear" else f"{output['domain']}:{output['level_id']}"


LABELS = ("unclear",) + tuple(f"{domain}:{level}" for domain, levels in LEVELS.items() for level in levels)

EVALUATED = register(
    EvaluatedAgent(
        spec=SPEC,
        input_fields=("objective",),
        labels=LABELS,
        payload=lambda item: payload(item["objective"]),
        label_of=label_of,
        score=classification_score,
    )
)
