"""Validation and hashing of block content (TipTap / ProseMirror JSON).

The server never trusts content as it arrives: only the node types, marks and
attributes of the editor's schema are accepted, links must be http(s) or
mailto, and the size and nesting depth are bounded.
"""

import hashlib
import json

from django.conf import settings

from .errors import ProgramError

# node type -> allowed attributes and a validator for each.
_ANY_STR_OR_NONE = lambda v: v is None or (isinstance(v, str) and len(v) <= 100)  # noqa: E731

NODE_ATTRS: dict[str, dict] = {
    "doc": {},
    "paragraph": {},
    "text": {},
    "heading": {"level": lambda v: isinstance(v, int) and 1 <= v <= 6},
    "bulletList": {},
    "orderedList": {
        "start": lambda v: isinstance(v, int) and 0 <= v <= 10_000,
        "type": lambda v: v is None or v in {"1", "a", "A", "i", "I"},
    },
    "listItem": {},
    "blockquote": {},
    "codeBlock": {"language": _ANY_STR_OR_NONE},
    "horizontalRule": {},
    "hardBreak": {},
}


def _safe_href(value) -> bool:
    if not isinstance(value, str) or len(value) > 2000:
        return False
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "mailto:"))


MARK_ATTRS: dict[str, dict] = {
    "bold": {},
    "italic": {},
    "strike": {},
    "code": {},
    "underline": {},
    "link": {"href": _safe_href, "target": _ANY_STR_OR_NONE, "rel": _ANY_STR_OR_NONE, "class": _ANY_STR_OR_NONE},
}

MAX_DEPTH = 30


def _fail(reason: str):
    raise ProgramError(f"the block content is not valid: {reason}", code="content_invalid")


def _check_attrs(kind: str, attrs, allowed: dict) -> None:
    if attrs is None:
        return
    if not isinstance(attrs, dict):
        _fail(f"{kind} attrs must be an object")
    for key, value in attrs.items():
        if key not in allowed:
            _fail(f"{kind} does not accept the attribute {key}")
        if not allowed[key](value):
            _fail(f"{kind}.{key} has an invalid value")


def _check_node(node, depth: int) -> None:
    if depth > MAX_DEPTH:
        _fail("nested too deeply")
    if not isinstance(node, dict):
        _fail("every node must be an object")
    kind = node.get("type")
    if kind not in NODE_ATTRS:
        _fail(f"unknown node type {kind!r}")
    unknown = set(node) - {"type", "attrs", "content", "text", "marks"}
    if unknown:
        _fail(f"unexpected keys {sorted(unknown)}")
    _check_attrs(kind, node.get("attrs"), NODE_ATTRS[kind])
    if kind == "text":
        if not isinstance(node.get("text"), str) or not node["text"]:
            _fail("text nodes need non-empty text")
        marks = node.get("marks", [])
        if not isinstance(marks, list):
            _fail("marks must be a list")
        for mark in marks:
            if not isinstance(mark, dict) or mark.get("type") not in MARK_ATTRS:
                _fail(f"unknown mark {mark!r}")
            if set(mark) - {"type", "attrs"}:
                _fail("unexpected keys in a mark")
            _check_attrs(mark["type"], mark.get("attrs"), MARK_ATTRS[mark["type"]])
        if "content" in node:
            _fail("text nodes have no content")
        return
    if "text" in node or "marks" in node:
        _fail(f"{kind} cannot carry text or marks")
    children = node.get("content", [])
    if not isinstance(children, list):
        _fail("content must be a list")
    for child in children:
        _check_node(child, depth + 1)


def canonical(content) -> str:
    return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def validate(content) -> dict:
    if not isinstance(content, dict) or content.get("type") != "doc":
        _fail("the root must be a doc node")
    _check_node(content, 0)
    if len(canonical(content).encode()) > settings.BLOCK_CONTENT_MAX_BYTES:
        _fail("the block is too large")
    return content


def content_hash(content) -> str:
    return hashlib.sha256(canonical(content).encode()).hexdigest()


EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}


_BLOCK_NODES = {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}


def plain_text(content) -> str:
    """Readable text of a block: paragraphs and list items on their own lines, marks dropped."""
    lines: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            lines.append("".join(current).strip())
            current.clear()

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        if kind == "text":
            current.append(node.get("text", ""))
        elif kind == "hardBreak":
            current.append("\n")
        for child in node.get("content", []) or []:
            walk(child)
        if kind in _BLOCK_NODES:
            flush()

    walk(content)
    flush()
    return "\n".join(line for line in lines if line)
