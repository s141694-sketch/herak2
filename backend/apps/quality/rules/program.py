"""Rules over a program version's tree (spec 5.2, decision D36).

Harak 1's objective rules run on every live objective block; leaf nodes are
checked for completeness; alignment links must exist; and every target
competency must reach at least one assessment, the one critical rule. Pure
Python over a snapshot of the version's rows, so it can run anywhere and is
deterministic: the same snapshot in any row order gives the same result.
"""

import hashlib
import json
from dataclasses import dataclass, field

from .harak1 import data as harak1_data
from .harak1.bloom import classify_objective
from .harak1.jsre import js_trim
from .harak1.matching import match_standards
from .harak1.objectives import check_objective
from .harak1.text import strip_tashkeel, unify_hamza

#: Harak 1's file (by hash) and the version of the Harak 2 rules below.
RULES_VERSION = "harak1-4e1256cf+harak2-1"

SEVERITY = {
    "competency_not_assessed": "critical",
    "node_missing_objective": "warning",
    "node_missing_assessment": "warning",
    "objective_not_aligned": "warning",
    "assessment_not_aligned": "warning",
    "link_to_deleted": "warning",
    "objective_unmeasurable": "warning",
    "objective_teacher_activity": "warning",
    "objective_process": "warning",
    "objective_topic": "warning",
    "objective_multi": "warning",
    "node_missing_activity": "info",
    "node_missing_reference": "info",
    "objective_unclassified": "info",
    "objective_components_missing": "info",
    "possible_competency_match": "info",
}

COMPONENTS = ["an", "verb", "learner", "content", "condition", "criterion"]
MATCHES_PER_OBJECTIVE = 3


@dataclass(frozen=True)
class NodeRow:
    key: str
    parent_key: str | None
    order: int
    title: str
    deleted: bool


@dataclass(frozen=True)
class BlockRow:
    key: str
    node_key: str
    type: str
    text: str
    content_hash: str
    deleted: bool
    order: int


@dataclass(frozen=True)
class LinkRow:
    kind: str
    source_key: str
    target_key: str | None
    competency_key: str | None


@dataclass(frozen=True)
class CompetencyRow:
    key: str
    code: str
    title: str


@dataclass(frozen=True)
class Snapshot:
    nodes: tuple[NodeRow, ...]
    blocks: tuple[BlockRow, ...]
    links: tuple[LinkRow, ...]
    #: Keys of the version's target competencies, in their order.
    targets: tuple[str, ...]
    #: Every competency of the version's framework, for lexical matching.
    competencies: tuple[CompetencyRow, ...]


@dataclass(frozen=True)
class Finding:
    kind: str
    node_key: str | None
    block_key: str | None = None
    competency_key: str | None = None
    confidence: str = "high"
    params: dict = field(default_factory=dict)

    @property
    def severity(self) -> str:
        return SEVERITY[self.kind]

    @property
    def fingerprint(self) -> str:
        """Identity of the problem across runs and versions (keys are stable); dismissals follow it. A link's
        target is part of it: one block can link to several deleted blocks."""
        parts = [self.kind, self.node_key, self.block_key, self.competency_key]
        if self.params.get("target_key"):
            parts.append(self.params["target_key"])
        identity = json.dumps(parts)
        return hashlib.sha256(identity.encode()).hexdigest()


@dataclass(frozen=True)
class ObjectiveResult:
    block_key: str
    node_key: str
    content_hash: str
    text: str
    verb: str
    level_id: int
    level: str
    domain: str | None
    confidence: str
    components: dict
    score: int
    errors: list
    dimension: dict | None


def _tree_order(snapshot: Snapshot) -> tuple[list[NodeRow], dict[str, list[NodeRow]]]:
    """Live nodes depth-first by (order, key); a node under a deleted or missing node is not live."""
    children: dict[str | None, list[NodeRow]] = {}
    for node in snapshot.nodes:
        children.setdefault(node.parent_key, []).append(node)
    for siblings in children.values():
        siblings.sort(key=lambda n: (n.order, n.key))
    ordered: list[NodeRow] = []
    live_children: dict[str, list[NodeRow]] = {}

    def walk(node: NodeRow) -> None:
        ordered.append(node)
        live_children[node.key] = [c for c in children.get(node.key, []) if not c.deleted]
        for child in live_children[node.key]:
            walk(child)

    for root in children.get(None, []):
        if not root.deleted:
            walk(root)
    return ordered, live_children


def _objective_text(text: str) -> str:
    """An objective block's text as one line, the way Harak 1 reads an objective."""
    return js_trim(" ".join(line for line in text.split("\n") if line))


def analyze(snapshot: Snapshot) -> tuple[list[ObjectiveResult], list[Finding]]:
    nodes, live_children = _tree_order(snapshot)
    live_nodes = {n.key for n in nodes}
    node_rank = {n.key: i for i, n in enumerate(nodes)}
    blocks = sorted(
        (b for b in snapshot.blocks if not b.deleted and b.node_key in live_nodes),
        key=lambda b: (node_rank[b.node_key], b.order, b.key),
    )
    live_blocks = {b.key: b for b in blocks}
    links = sorted(
        snapshot.links, key=lambda link: (link.kind, link.source_key, link.target_key or "", link.competency_key or "")
    )
    live_links = [
        link
        for link in links
        if link.source_key in live_blocks and (link.target_key is None or link.target_key in live_blocks)
    ]
    competencies = {c.key: c for c in snapshot.competencies}
    findings: list[Finding] = []
    objectives: list[ObjectiveResult] = []

    # Harak 1's rules on each objective, and lexical matches for objectives not linked to a competency.
    linked_to_competency = {link.source_key for link in live_links if link.kind == "objective_competency"}
    for b in (b for b in blocks if b.type == "objective"):
        text = _objective_text(b.text)
        classified = classify_objective(text)
        quality = check_objective(text, classified)
        objectives.append(
            ObjectiveResult(
                b.key,
                b.node_key,
                b.content_hash,
                text,
                classified["verb"],
                classified["levelId"],
                classified["level"],
                classified["domain"],
                classified["confidence"],
                quality["components"],
                quality["score"],
                quality["errors"],
                quality["dimension"],
            )
        )
        if classified["domain"] is None:
            findings.append(
                Finding(
                    "objective_unclassified", b.node_key, b.key, confidence="low", params={"verb": classified["verb"]}
                )
            )
        verb = unify_hamza(strip_tashkeel(classified["verb"]))
        if verb[:1] == "ت":
            verb = "ي" + verb[1:]
        if verb in harak1_data.UNMEASURABLE_VERBS:
            findings.append(
                Finding(
                    "objective_unmeasurable",
                    b.node_key,
                    b.key,
                    confidence="medium",
                    params={"verb": classified["verb"]},
                )
            )
        for error in ("teacher-activity", "process", "topic", "multi"):
            if error in quality["errors"]:
                findings.append(Finding(f"objective_{error.replace('-', '_')}", b.node_key, b.key, confidence="medium"))
        missing = [c for c in COMPONENTS if not quality["components"][c]]
        if missing:
            findings.append(
                Finding(
                    "objective_components_missing", b.node_key, b.key, confidence="medium", params={"missing": missing}
                )
            )
        if b.key not in linked_to_competency and competencies:
            pool = [{"id": c.key, "code": c.code, "text": c.title} for c in snapshot.competencies]
            for match in match_standards([text], pool)[:MATCHES_PER_OBJECTIVE]:
                findings.append(
                    Finding(
                        "possible_competency_match",
                        b.node_key,
                        b.key,
                        match["standardId"],
                        confidence=match["confidence"],
                        params={"score": match["score"]},
                    )
                )

    # Completeness of leaf nodes (Harak 1's lessons).
    types_of: dict[str, set[str]] = {}
    for b in blocks:
        types_of.setdefault(b.node_key, set()).add(b.type)
    for node in nodes:
        if live_children[node.key]:
            continue
        types = types_of.get(node.key, set())
        for kind, type_ in (
            ("node_missing_objective", "objective"),
            ("node_missing_assessment", "assessment"),
            ("node_missing_activity", "activity"),
            ("node_missing_reference", "reference"),
        ):
            if type_ not in types:
                findings.append(Finding(kind, node.key))

    # Links must exist, and must not point at deleted blocks.
    for link in links:
        if link.source_key in live_blocks and link.target_key is not None and link.target_key not in live_blocks:
            source = live_blocks[link.source_key]
            findings.append(
                Finding(
                    "link_to_deleted",
                    source.node_key,
                    source.key,
                    params={"link": link.kind, "target_key": link.target_key},
                )
            )
    aligned_objectives = {
        link.source_key for link in live_links if link.kind in ("objective_competency", "objective_parent")
    }
    aligned_assessments = {link.source_key for link in live_links if link.kind == "assessment_objective"}
    for b in blocks:
        if b.type == "objective" and b.key not in aligned_objectives:
            findings.append(Finding("objective_not_aligned", b.node_key, b.key))
        if b.type == "assessment" and b.key not in aligned_assessments:
            findings.append(Finding("assessment_not_aligned", b.node_key, b.key))

    # The mandatory rule: every target competency reaches at least one assessment.
    direct: dict[str, set[str]] = {}
    parents: dict[str, list[str]] = {}
    for link in live_links:
        if link.kind == "objective_competency" and link.competency_key:
            direct.setdefault(link.source_key, set()).add(link.competency_key)
        elif link.kind == "objective_parent" and link.target_key:
            parents.setdefault(link.source_key, []).append(link.target_key)

    def serves(objective: str, seen: frozenset = frozenset()) -> set[str]:
        if objective in seen:
            return set()
        found = set(direct.get(objective, set()))
        for parent in parents.get(objective, []):
            found |= serves(parent, seen | {objective})
        return found

    covered: set[str] = set()
    for link in live_links:
        if link.kind == "assessment_objective" and live_blocks[link.source_key].type == "assessment":
            covered |= serves(link.target_key)
    served = set()
    for b in blocks:
        if b.type == "objective":
            served |= serves(b.key)
    root = nodes[0].key if nodes else None
    for competency in snapshot.targets:
        if competency not in covered:
            findings.append(
                Finding(
                    "competency_not_assessed", root, None, competency, params={"has_objective": competency in served}
                )
            )

    block_rank = {key: i for i, key in enumerate(live_blocks)}
    findings.sort(
        key=lambda f: (node_rank.get(f.node_key, -1), block_rank.get(f.block_key, -1), f.kind, f.competency_key or "")
    )
    return objectives, findings
