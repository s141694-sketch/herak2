"""Comparing two versions of one program by stable keys (task 2.7).

Soft-deleted rows count as absent. A row present in both versions is
"modified" when its own substance changed (title, content, type), "moved"
when only its place changed (parent or node, order), else "unchanged".
"""

from .content import plain_text
from .errors import ProgramError
from .models import ProgramVersion

CHANGES = ("added", "removed", "modified", "moved", "unchanged")


def _nodes(version: ProgramVersion) -> dict[str, dict]:
    return {
        str(n.node_key): {
            "node_key": str(n.node_key),
            "title": n.title,
            "level": n.level,
            "order": n.order,
            "parent": str(n.parent.node_key) if n.parent else None,
        }
        for n in version.nodes.select_related("parent").filter(deleted=False)
    }


def _blocks(version: ProgramVersion) -> dict[str, dict]:
    return {
        str(b.block_key): {
            "block_key": str(b.block_key),
            "type": b.type,
            "node": str(b.node.node_key),
            "order": b.order,
            "content_hash": b.content_hash,
            "content": b.content,
        }
        for b in version.blocks.select_related("node").filter(deleted=False)
    }


def _compare(before: dict[str, dict], after: dict[str, dict], substance: list[str], place: list[str]) -> list[dict]:
    entries = []
    for key in list(after) + [k for k in before if k not in after]:
        old, new = before.get(key), after.get(key)
        if old is None:
            change, fields = "added", []
        elif new is None:
            change, fields = "removed", []
        else:
            changed_substance = [f for f in substance if old[f] != new[f]]
            changed_place = [f for f in place if old[f] != new[f]]
            fields = changed_substance + changed_place
            change = "modified" if changed_substance else "moved" if changed_place else "unchanged"
        entries.append({"key": key, "change": change, "fields": fields, "before": old, "after": new})
    return entries


def _links(version: ProgramVersion, present_blocks: set[str]) -> dict[tuple, dict]:
    found = {}
    for link in version.alignment_links.select_related("source", "target_block", "target_competency"):
        source = str(link.source.block_key)
        target = str(link.target_block.block_key) if link.target_block else None
        if source not in present_blocks or (target is not None and target not in present_blocks):
            continue
        competency = link.target_competency
        identity = (link.kind, source, target, str(competency.competency_key) if competency else None)
        found[identity] = {
            "kind": link.kind,
            "source_key": source,
            "target_block_key": target,
            "competency_key": identity[3],
            "competency_code": competency.code if competency else None,
        }
    return found


def _targets(version: ProgramVersion) -> dict[str, dict]:
    return {
        str(t.competency.competency_key): {
            "competency_key": str(t.competency.competency_key),
            "code": t.competency.code,
            "title": t.competency.title,
        }
        for t in version.targets.select_related("competency")
    }


def _summary(entries: list[dict]) -> dict[str, int]:
    counts = dict.fromkeys(CHANGES, 0)
    for entry in entries:
        counts[entry["change"]] += 1
    return counts


def diff_versions(before: ProgramVersion, after: ProgramVersion) -> dict:
    if before.program_id != after.program_id:
        raise ProgramError("only versions of the same program can be compared", code="diff_programs_differ")

    node_entries = _compare(_nodes(before), _nodes(after), substance=["title"], place=["parent", "order"])
    for entry in node_entries:
        entry["node_key"] = entry.pop("key")

    blocks_before, blocks_after = _blocks(before), _blocks(after)
    block_entries = _compare(blocks_before, blocks_after, substance=["content_hash", "type"], place=["node", "order"])
    for entry in block_entries:
        entry["block_key"] = entry.pop("key")
        entry["fields"] = ["content" if f == "content_hash" else f for f in entry["fields"]]
        entry["text_before"] = plain_text(entry["before"]["content"]) if entry["before"] else None
        entry["text_after"] = plain_text(entry["after"]["content"]) if entry["after"] else None
        for side in ("before", "after"):
            if entry[side]:
                entry[side] = {k: v for k, v in entry[side].items() if k != "content"}

    links_before = _links(before, set(blocks_before))
    links_after = _links(after, set(blocks_after))
    targets_before, targets_after = _targets(before), _targets(after)

    return {
        "from": {"id": before.pk, "number": before.number, "status": before.status},
        "to": {"id": after.pk, "number": after.number, "status": after.status},
        "nodes": node_entries,
        "blocks": block_entries,
        "links": {
            "added": [links_after[k] for k in links_after if k not in links_before],
            "removed": [links_before[k] for k in links_before if k not in links_after],
        },
        "targets": {
            "added": [targets_after[k] for k in targets_after if k not in targets_before],
            "removed": [targets_before[k] for k in targets_before if k not in targets_after],
        },
        "summary": {"nodes": _summary(node_entries), "blocks": _summary(block_entries)},
    }
