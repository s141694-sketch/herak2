"""Rows <-> live-document form, on the Django side (task 3.3).

Rows arrive already materialized by the collaboration service. Django checks
them like any other input and applies them to the draft by stable key, so
blocks keep their ids (and their links and future findings) across saves.
"""

import uuid

from django.db import transaction

from apps.audit.services import record
from apps.programs import content as block_content
from apps.programs import services as program_services
from apps.programs.errors import ProgramError
from apps.programs.models import AlignmentLink, Block, Node, ProgramVersion
from apps.programs.signals import content_changed


class MaterializationError(Exception):
    """The rows cannot be applied; the last good rows stay in place."""


def rows_from_version(version: ProgramVersion) -> dict:
    nodes = list(version.nodes.select_related("parent").order_by("level", "order", "pk"))
    return {
        "nodes": [
            {
                "node_key": str(n.node_key),
                "parent_key": str(n.parent.node_key) if n.parent else None,
                "level": n.level,
                "order": n.order,
                "title": n.title,
                "deleted": n.deleted,
            }
            for n in nodes
        ],
        "blocks": [
            {
                "block_key": str(b.block_key),
                "node_key": str(b.node.node_key),
                "type": b.type,
                "order": b.order,
                "deleted": b.deleted,
                "content": b.content,
            }
            for b in version.blocks.select_related("node").order_by("node_id", "order", "pk")
        ],
        "links": [
            {
                "link_key": str(link.link_key),
                "kind": link.kind,
                "source_key": str(link.source.block_key),
                "target_key": str(link.target_block.block_key) if link.target_block else None,
                "competency_key": str(link.target_competency.competency_key) if link.target_competency else None,
            }
            for link in version.alignment_links.select_related("source", "target_block", "target_competency")
        ],
    }


def _uuid(value, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError) as exc:
        raise MaterializationError(f"{what} is not a valid key: {value!r}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


@transaction.atomic
def apply_rows(version: ProgramVersion, rows: dict, *, actor=None) -> dict:
    """Applies materialized rows to an editable draft. Raises MaterializationError and changes nothing on failure."""
    level_count = version.program.template_version.levels.count()
    _require(isinstance(rows, dict), "rows must be an object")

    existing_nodes = {str(n.node_key): n for n in Node.objects.filter(version=version)}
    nodes: dict[str, Node] = {}
    for row in rows.get("nodes", []):
        key = _uuid(row.get("node_key"), "node_key")
        _require(key not in nodes, f"node {key} appears twice")
        parent_key = row.get("parent_key")
        parent = None
        if parent_key is not None:
            parent = nodes.get(_uuid(parent_key, "parent_key"))
            _require(parent is not None, f"node {key} comes before its parent")
        level = 0 if parent is None else parent.level + 1
        _require(row.get("level") == level, f"node {key} has level {row.get('level')}, its place gives {level}")
        _require(level < level_count, f"node {key} is deeper than the template's {level_count} levels")
        title = row.get("title")
        _require(isinstance(title, str) and len(title) <= 500, f"node {key} has an invalid title")
        order = row.get("order")
        _require(isinstance(order, int) and order >= 0, f"node {key} has an invalid order")
        fields = {"parent": parent, "level": level, "order": order, "title": title, "deleted": bool(row.get("deleted"))}
        node = existing_nodes.get(key)
        if node is None:
            node = Node.objects.create(version=version, node_key=key, **fields)
        elif any(getattr(node, f) != v for f, v in fields.items()):
            for f, v in fields.items():
                setattr(node, f, v)
            node.save()
        nodes[key] = node
    for key, node in existing_nodes.items():
        if key not in nodes and not node.deleted:
            node.deleted = True
            node.save()

    existing_blocks = {str(b.block_key): b for b in Block.objects.filter(version=version)}
    blocks: dict[str, Block] = {}
    changed: list[str] = []
    for row in rows.get("blocks", []):
        key = _uuid(row.get("block_key"), "block_key")
        _require(key not in blocks, f"block {key} appears twice")
        node = nodes.get(_uuid(row.get("node_key"), "node_key"))
        _require(node is not None, f"block {key} points at a missing node")
        _require(row.get("type") in Block.Type.values, f"block {key} has an unknown type")
        order = row.get("order")
        _require(isinstance(order, int) and order >= 0, f"block {key} has an invalid order")
        try:
            body = block_content.validate(row.get("content"))
        except ProgramError as exc:
            raise MaterializationError(f"block {key}: {exc.detail}") from exc
        digest = block_content.content_hash(body)
        fields = {
            "node": node,
            "type": row["type"],
            "order": order,
            "deleted": bool(row.get("deleted")),
            "content": body,
            "content_hash": digest,
        }
        block = existing_blocks.get(key)
        if block is None:
            block = Block.objects.create(version=version, block_key=key, **fields)
            changed.append(key)
        elif any(getattr(block, f) != v for f, v in fields.items()):
            if block.content_hash != digest or block.type != row["type"]:
                changed.append(key)
            for f, v in fields.items():
                setattr(block, f, v)
            block.save()
        blocks[key] = block
    for key, block in existing_blocks.items():
        if key not in blocks and not block.deleted:
            block.deleted = True
            block.save()
            changed.append(key)

    # Links follow the document exactly; invalid ones are skipped and reported, never fatal (decision D29).
    competencies = {str(c.competency_key): c for c in version.framework_version.competencies.all()}
    AlignmentLink.objects.filter(version=version).delete()
    skipped: list[str] = []
    seen_links: set[tuple] = set()
    for row in rows.get("links", []):
        key = _uuid(row.get("link_key"), "link_key")
        source = blocks.get(str(row.get("source_key")))
        target = blocks.get(str(row.get("target_key"))) if row.get("target_key") else None
        competency = competencies.get(str(row.get("competency_key"))) if row.get("competency_key") else None
        identity = (
            row.get("kind"),
            str(row.get("source_key")),
            str(row.get("target_key")),
            str(row.get("competency_key")),
        )
        missing_end = (
            source is None
            or (row.get("target_key") and target is None)
            or (row.get("competency_key") and competency is None)
        )
        if (
            missing_end
            or identity in seen_links
            or program_services.link_problem(version, row.get("kind"), source, target, competency)
        ):
            skipped.append(key)
            continue
        seen_links.add(identity)
        AlignmentLink.objects.create(
            version=version,
            link_key=key,
            kind=row["kind"],
            source=source,
            target_block=target,
            target_competency=competency,
            created_by=actor or version.created_by,
        )

    if changed:
        record("program_version.materialized", actor=actor, target=version, payload={"changed_blocks": changed})
    content_changed.send(sender=ProgramVersion, version=version)
    return {"changed_blocks": changed, "skipped_links": skipped}
