"""Drafting agent (spec 5.3): a sound rewrite of a weak objective, and a first outline built from the competencies a
version targets.

It suggests only. Harak's own rules decide which objectives are weak enough to rewrite and which answers are good
enough to show; the author accepts or rejects what is shown, and an accepted suggestion is written into the live
document by the author's own editor, never by the server (D45, D46).
"""

from apps.ai.gateway import AgentSpec, call
from apps.evals.evaluation import EvaluatedAgent, register
from apps.quality.rules.harak1.bloom import classify_objective
from apps.quality.rules.harak1.objectives import check_objective

from .alignment import Competency, well_formed

PROMPT_VERSION = "2026-10-03.1"

OBJECTIVE_FORM = (
    'A sound objective starts with "أن" followed by one measurable present-tense verb, names the trainee '
    "(المتدرب), states the content, and where natural a condition and a criterion. One outcome only; no teacher "
    "activity, no topic-only phrasing, no unmeasurable verbs such as يفهم or يعرف."
)

REWRITE_INSTRUCTIONS = f"""You rewrite one weak learning objective of a vocational training programme so that it
becomes a sound behavioural objective with the same intent. It is usually written in Arabic; write the rewrite in
its language.

The data gives the objective, the problems Harak's rules found in it (codes such as missing_verb, missing_learner,
verb_unclassified, unmeasurable, teacher-activity, multi), and the competencies it is linked to, if any.
{OBJECTIVE_FORM} Keep the subject matter and level of the original and add nothing it does not imply. Give a short
explanation of what you changed, in the objective's language, and your confidence."""

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string", "minLength": 8, "maxLength": 400},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string", "maxLength": 600},
    },
    "required": ["objective", "confidence", "explanation"],
    "additionalProperties": False,
}

OUTLINE_INSTRUCTIONS = f"""You draft a first outline of a vocational training programme from the competencies it
targets: a tree of nodes on the levels of the organisation's structure template, and learning objectives that serve the
competencies. Write in the language of the competencies (usually Arabic).

The data gives the programme's title and target role, the names of the template's levels from the top (for
example وحدة then درس), and the target competencies with their codes. Return the nodes as a flat list in order:
each has a short ref (n1, n2, ...), the ref of its parent ("" for a node on the first level) and a short title.
A parent always comes before its children, and no node is deeper than the number of levels given. Attach the
objectives to nodes of the deepest level you use; each names the code of the one competency it serves, and
every competency is served by at least one objective. {OBJECTIVE_FORM} Keep it small: at most 30 nodes and 60
objectives. Give a short explanation of the outline and your confidence."""

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "minLength": 1, "maxLength": 20},
                    "parent": {"type": "string", "maxLength": 20},
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                },
                "required": ["ref", "parent", "title"],
                "additionalProperties": False,
            },
        },
        "objectives": {
            "type": "array",
            "minItems": 1,
            "maxItems": 60,
            "items": {
                "type": "object",
                "properties": {
                    "node": {"type": "string", "maxLength": 20},
                    "competency": {"type": "string", "maxLength": 50},
                    "text": {"type": "string", "minLength": 8, "maxLength": 400},
                },
                "required": ["node", "competency", "text"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string", "maxLength": 800},
    },
    "required": ["nodes", "objectives", "confidence", "explanation"],
    "additionalProperties": False,
}

REWRITE = AgentSpec(
    name="drafting_rewrite",
    prompt_version=PROMPT_VERSION,
    instructions=REWRITE_INSTRUCTIONS,
    schema=REWRITE_SCHEMA,
    max_tokens=1500,
    effort="medium",
)
OUTLINE = AgentSpec(
    name="drafting_outline",
    prompt_version=PROMPT_VERSION,
    instructions=OUTLINE_INSTRUCTIONS,
    schema=OUTLINE_SCHEMA,
    max_tokens=8000,
    effort="medium",
)


class OutlineRejected(Exception):
    """Nothing usable is left of an outline once the rules and the version's limits are applied."""


def problems_of(objective: str) -> list[str]:
    """What Harak's rules find missing or wrong in an objective, as codes the rewrite is asked to fix."""
    classified = classify_objective(objective)
    quality = check_objective(objective, classified)
    problems = {f"missing_{part}" for part, present in quality["components"].items() if not present}
    if quality["components"]["verb"] and classified["domain"] is None:
        problems.add("verb_unclassified")
    problems.update(quality["errors"])
    return sorted(problems)


def needs_rewrite(objective: str) -> bool:
    """Only objectives Harak's rules do not accept are sent for a rewrite."""
    return not well_formed(objective)


def rewrite_payload(objective: str, competencies: list[Competency]) -> dict:
    return {
        "objective": objective,
        "problems": problems_of(objective),
        "competencies": [competency.as_payload() for competency in competencies],
    }


def outline_payload(title: str, target_role: str, levels: list[str], competencies: list[Competency]) -> dict:
    return {
        "programme": {"title": title, "target_role": target_role},
        "levels": list(levels),
        "competencies": [competency.as_payload() for competency in competencies],
    }


def rewrite(objective: str, competencies: list[Competency], *, organization_id: int) -> tuple[dict, str]:
    result = call(
        REWRITE,
        rewrite_payload(objective, competencies),
        organization_id=organization_id,
        accept=lambda output: judge_rewrite(objective, output)[0] == "ready",
    )
    return result.output, result.model


def outline(
    title: str, target_role: str, levels: list[str], competencies: list[Competency], *, organization_id: int
) -> tuple[dict, str]:
    codes = {competency.code for competency in competencies}

    def usable(output: dict) -> bool:
        try:
            shape_outline(output, level_count=len(levels), competency_codes=codes)
        except OutlineRejected:
            return False
        return True

    result = call(
        OUTLINE,
        outline_payload(title, target_role, levels, competencies),
        organization_id=organization_id,
        accept=usable,
    )
    return result.output, result.model


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def judge_rewrite(original: str, output: dict) -> tuple[str, str | None]:
    """("ready", None) when the rewrite may be shown; ("rejected", why) when Harak's rules or common sense refuse it."""
    text = output["objective"].strip()
    if _same(text, original):
        return "rejected", "unchanged"
    if not well_formed(text):
        return "rejected", "not_sound"
    return "ready", None


def shape_outline(output: dict, *, level_count: int, competency_codes: set[str]) -> tuple[dict, dict]:
    """The part of an outline that can be written into the version: nodes within the template's depth whose parent
    is kept, and objectives the rules accept, for a competency the version targets, on a kept node.

    Returns the outline and how many nodes and objectives were dropped. Raises OutlineRejected when no node or no
    objective is left.
    """
    levels: dict[str, int] = {}
    nodes: list[dict] = []
    for node in output.get("nodes", []):
        ref, parent, title = node["ref"].strip(), node["parent"].strip(), " ".join(node["title"].split())
        level = 0 if parent == "" else levels.get(parent, -2) + 1
        if not ref or ref in levels or level < 0 or level >= level_count or not title:
            continue
        levels[ref] = level
        nodes.append({"ref": ref, "parent": parent, "title": title})
    objectives: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for objective in output.get("objectives", []):
        node, code, text = objective["node"].strip(), objective["competency"].strip(), objective["text"].strip()
        if node not in levels or code not in competency_codes or (node, text) in seen or not well_formed(text):
            continue
        seen.add((node, text))
        objectives.append({"node": node, "competency": code, "text": text})
    if not nodes or not objectives:
        raise OutlineRejected("no node or no objective of the outline can be used")
    dropped = {
        "nodes": len(output.get("nodes", [])) - len(nodes),
        "objectives": len(output.get("objectives", [])) - len(objectives),
    }
    return {"nodes": nodes, "objectives": objectives}, dropped


def _competencies(text: str) -> list[Competency]:
    """Golden-set cells list competencies one per line as "CODE: title"."""
    found = []
    for line in (text or "").splitlines():
        code, _, title = line.partition(":")
        if code.strip() and title.strip():
            found.append(Competency(code.strip(), title.strip()))
    return found


def _outline_label(output: dict, payload: dict) -> str:
    codes = {competency["code"] for competency in payload["competencies"]}
    try:
        shaped, _ = shape_outline(output, level_count=len(payload["levels"]), competency_codes=codes)
    except OutlineRejected:
        return "rejected"
    return "ok" if {objective["competency"] for objective in shaped["objectives"]} == codes else "partial"


register(
    EvaluatedAgent(
        spec=REWRITE,
        input_fields=("objective", "competencies"),
        # Experts mark the weak objectives that can be rewritten soundly; the score is the share of rewrites Harak's
        # rules accept. Whether the intent was kept is judged by authors accepting or rejecting them in use.
        labels=("ok",),
        payload=lambda item: rewrite_payload(item["objective"], _competencies(item.get("competencies", ""))),
        label_of=lambda output: "ok" if well_formed(output["objective"]) else "rejected",
        label_with_input=lambda output, payload: (
            "ok" if judge_rewrite(payload["objective"], output)[0] == "ready" else "rejected"
        ),
        score=lambda gold, predicted: {
            "well_formed": sum(g == p for g, p in zip(gold, predicted, strict=True)) / len(gold)
        },
    )
)

register(
    EvaluatedAgent(
        spec=OUTLINE,
        input_fields=("programme_title", "target_role", "levels", "competencies"),
        # Complete: every competency given is served by an objective the rules accept, within the template's depth.
        labels=("ok",),
        payload=lambda item: outline_payload(
            item["programme_title"],
            item.get("target_role", ""),
            [level.strip() for level in item["levels"].split("/") if level.strip()],
            _competencies(item["competencies"]),
        ),
        label_of=lambda output: "ok",
        label_with_input=_outline_label,
        score=lambda gold, predicted: {"complete": sum(p == "ok" for p in predicted) / len(gold)},
    )
)
