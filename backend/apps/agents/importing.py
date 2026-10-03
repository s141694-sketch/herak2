"""Import agent (spec 5.3, task 4.9): curriculum text laid out on the version's tree and blocks.

Rules first: the text is read and structured exactly as Harak 1 does (``read_text_document`` and ``structure``,
both checked for parity with Harak 1), and that structure is laid onto the template's levels. The agent then
proposes a better distribution, but its blocks cite source lines by number, so it cannot add text that is not in
the document; only node titles are its own words. The author confirms before anything reaches the document
(D48).
"""

from apps.ai.gateway import AgentSpec, call
from apps.evals.evaluation import EvaluatedAgent, register
from apps.quality.rules.harak1 import structure, text
from apps.quality.rules.harak1.jsre import js_trim

PROMPT_VERSION = "2026-10-03.1"

#: Longer documents are laid out by the rules alone: one answer could not cite every line.
MAX_AI_LINES = 1500
MAX_TEXT_CHARS = 200_000

BLOCK_TYPES = ["objective", "content", "activity", "assessment", "reference"]
SECTION_BLOCKS = {
    "objectives": "objective",
    "activities": "activity",
    "assessments": "assessment",
    "references": "reference",
}

INSTRUCTIONS = """You lay out the text of a vocational training curriculum on the tree of a programme. The text is
usually Arabic.

The data gives the names of the structure template's levels from the top (for example وحدة then درس), the
document's lines, each with its number n, and the layout Harak's rules found (units, lessons and blocks). Improve
that layout: place the lines the rules left out, fix lines filed under the wrong kind, and use the template's
levels. Return nodes as a flat list in order: each has a short ref (n1, n2, ...), the ref of its parent ("" for
the first level) and a short title, usually the heading line itself; a parent comes before its children, and no
node is deeper than the number of levels given. Return blocks in reading order: each names its node, its type
(objective, content, activity, assessment or reference) and the numbers of the lines it is made of, in order. Never
write text of your own in a block: cite lines. Use each line at most once; leave out headings you used as titles
and lines that are not curriculum content (page furniture, publisher notes). Give a short explanation and your
confidence."""

SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 200,
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "minLength": 1, "maxLength": 20},
                    "parent": {"type": "string", "maxLength": 20},
                    "title": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                "required": ["ref", "parent", "title"],
                "additionalProperties": False,
            },
        },
        "blocks": {
            "type": "array",
            "maxItems": 2000,
            "items": {
                "type": "object",
                "properties": {
                    "node": {"type": "string", "maxLength": 20},
                    "type": {"type": "string", "enum": BLOCK_TYPES},
                    "lines": {"type": "array", "minItems": 1, "items": {"type": "integer"}},
                },
                "required": ["node", "type", "lines"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string", "maxLength": 800},
    },
    "required": ["nodes", "blocks", "confidence", "explanation"],
    "additionalProperties": False,
}

SPEC = AgentSpec(
    name="import",
    prompt_version=PROMPT_VERSION,
    instructions=INSTRUCTIONS,
    schema=SCHEMA,
    max_tokens=16000,
    effort="medium",
)


class ImportTextInvalid(Exception):
    """Harak 1's reader refuses the text (no Arabic text to speak of, say); ``code`` is Harak 1's."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ImportRejected(Exception):
    """Nothing usable is left of the agent's layout."""


def read(source: str) -> dict:
    """The document as Harak 1 reads and structures it, and its non-empty lines in order."""
    if len(source) > MAX_TEXT_CHARS:
        raise ImportTextInvalid("TOO_LONG", f"the text is longer than {MAX_TEXT_CHARS} characters")
    try:
        doc = text.read_text_document("import.txt", source)
    except text.ReaderError as exc:
        raise ImportTextInvalid(exc.code, str(exc)) from exc
    lines = [js_trim(raw) for page in doc["pages"] for raw in page["text"].split("\n")]
    return {"doc": doc, "struct": structure.structure(doc), "lines": [line for line in lines if line]}


def _normalized(line: str) -> str:
    return " ".join(line.split()).rstrip(":：").strip()


def _is_section_heading(line: str) -> bool:
    return any(structure.match_pattern(line, section) for section in structure.SECTION_TYPES)


def _unplaced(lines: list[str], nodes: list[dict], blocks: list[dict], cited: set[int] | None = None) -> list[str]:
    """Lines that are in no block and are not a node's title or a section heading."""
    titles = {_normalized(node["title"]) for node in nodes}
    texts = [" ".join(block["text"].split()) for block in blocks]
    unplaced = []
    for index, line in enumerate(lines):
        if cited is not None and index in cited:
            continue
        flat = " ".join(line.split())
        if _normalized(line) in titles or _is_section_heading(line):
            continue
        if cited is None and any(flat in block_text for block_text in texts):
            continue
        unplaced.append(line)
    return unplaced


def _title(value: str) -> str:
    return "".join(list(" ".join(value.split()))[:500])


def rules_proposal(read_result: dict, *, level_count: int) -> dict:
    """Harak 1's units and lessons on the template's first two levels, its sections as blocks."""
    nodes: list[dict] = []
    blocks: list[dict] = []
    for u, unit in enumerate(read_result["struct"]["units"], start=1):
        unit_ref = f"u{u}"
        nodes.append({"ref": unit_ref, "parent": "", "title": _title(unit["title"])})
        for le, lesson in enumerate(unit["lessons"], start=1):
            target = unit_ref
            folds = lesson["implicit"] and lesson["title"] == unit["title"]
            if level_count >= 2 and not folds:
                target = f"{unit_ref}l{le}"
                nodes.append({"ref": target, "parent": unit_ref, "title": _title(lesson["title"])})
            for section, block_type in SECTION_BLOCKS.items():
                blocks.extend({"node": target, "type": block_type, "text": item["text"]} for item in lesson[section])
    return {
        "source": "rules",
        "nodes": nodes,
        "blocks": blocks,
        "unplaced": _unplaced(read_result["lines"], nodes, blocks),
        "warnings": [warning["code"] for warning in read_result["struct"]["warnings"]],
    }


def payload(read_result: dict, levels: list[str], rules: dict) -> dict:
    return {
        "levels": list(levels),
        "lines": [{"n": index, "text": line} for index, line in enumerate(read_result["lines"])],
        "rules": {key: rules[key] for key in ("nodes", "blocks", "unplaced")},
    }


def distribute(read_result: dict, levels: list[str], *, organization_id: int) -> tuple[dict, str]:
    rules = rules_proposal(read_result, level_count=len(levels))
    result = call(SPEC, payload(read_result, levels, rules), organization_id=organization_id)
    return result.output, result.model


def shape_import(output: dict, *, lines: list[str], level_count: int) -> dict:
    """The part of the agent's layout that can be used: nodes within the template's depth whose parent is kept,
    blocks on a kept node made of lines of the document, each line used once. Raises ImportRejected when no node
    or no block is left."""
    levels: dict[str, int] = {}
    nodes: list[dict] = []
    for node in output.get("nodes", []):
        ref, parent, title = node["ref"].strip(), node["parent"].strip(), _title(node["title"])
        level = 0 if parent == "" else levels.get(parent, -2) + 1
        if not ref or ref in levels or level < 0 or level >= level_count or not title:
            continue
        levels[ref] = level
        nodes.append({"ref": ref, "parent": parent, "title": title})
    blocks: list[dict] = []
    cited: set[int] = set()
    for block in output.get("blocks", []):
        if block["node"] not in levels or block["type"] not in BLOCK_TYPES:
            continue
        own = []
        for index in block["lines"]:
            if isinstance(index, int) and 0 <= index < len(lines) and index not in cited:
                cited.add(index)
                own.append(index)
        if own:
            blocks.append({"node": block["node"], "type": block["type"], "text": "\n".join(lines[i] for i in own)})
    if not nodes or not blocks:
        raise ImportRejected("no node or no block of the layout can be used")
    return {
        "source": "ai",
        "nodes": nodes,
        "blocks": blocks,
        "unplaced": _unplaced(lines, nodes, blocks, cited),
        "dropped": {
            "nodes": len(output.get("nodes", [])) - len(nodes),
            "blocks": len(output.get("blocks", [])) - len(blocks),
        },
        "warnings": [],
    }


def _levels(value: str) -> list[str]:
    return [level.strip() for level in value.split("/") if level.strip()]


def _payload_of(item: dict) -> dict:
    read_result = read(item["text"])
    levels = _levels(item["levels"])
    return payload(read_result, levels, rules_proposal(read_result, level_count=len(levels)))


def _label(output: dict, given: dict) -> str:
    lines = [line["text"] for line in given["lines"]]
    try:
        shaped = shape_import(output, lines=lines, level_count=len(given["levels"]))
    except ImportRejected:
        return "rejected"
    return "ok" if not shaped["unplaced"] else "partial"


register(
    EvaluatedAgent(
        spec=SPEC,
        input_fields=("text", "levels"),
        # Experts mark the documents a sound layout exists for. "complete": the layout is usable and places every
        # line; "valid": it is usable at all. Whether lines landed in the right place is judged by authors, who
        # confirm or reject every import, and their decisions are recorded.
        labels=("ok",),
        payload=_payload_of,
        label_of=lambda output: "ok",
        label_with_input=_label,
        score=lambda gold, predicted: {
            "complete": sum(p == "ok" for p in predicted) / len(gold),
            "valid": sum(p in ("ok", "partial") for p in predicted) / len(gold),
        },
    )
)
