"""Reads a version's rows into the plain snapshot the rules work on."""

from apps.programs.content import plain_text
from apps.programs.models import AlignmentLink, Block, Node, ProgramTarget, ProgramVersion

from .rules.program import BlockRow, CompetencyRow, LinkRow, NodeRow, Snapshot


def load_snapshot(version: ProgramVersion) -> Snapshot:
    nodes = Node.objects.filter(version=version).select_related("parent")
    blocks = Block.objects.filter(version=version).select_related("node")
    links = AlignmentLink.objects.filter(version=version).select_related("source", "target_block", "target_competency")
    targets = ProgramTarget.objects.filter(version=version).select_related("competency")
    return Snapshot(
        nodes=tuple(
            NodeRow(str(n.node_key), str(n.parent.node_key) if n.parent else None, n.order, n.title, n.deleted)
            for n in nodes
        ),
        blocks=tuple(
            BlockRow(
                str(b.block_key),
                str(b.node.node_key),
                b.type,
                plain_text(b.content),
                b.content_hash,
                b.deleted,
                b.order,
            )
            for b in blocks
        ),
        links=tuple(
            LinkRow(
                link.kind,
                str(link.source.block_key),
                str(link.target_block.block_key) if link.target_block else None,
                str(link.target_competency.competency_key) if link.target_competency else None,
            )
            for link in links
        ),
        targets=tuple(str(t.competency.competency_key) for t in targets),
        competencies=tuple(
            CompetencyRow(str(c.competency_key), c.code, c.title) for c in version.framework_version.competencies.all()
        ),
    )
