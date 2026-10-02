"""Creating a new draft version as a copy of an existing one. Rows keep their stable keys."""

from django.db.models import Max

from apps.audit.services import record

from .errors import ProgramError
from .models import AlignmentLink, Block, Node, ProgramTarget, ProgramVersion


def create_draft_copy(source: ProgramVersion, *, actor) -> ProgramVersion:
    program = source.program
    if program.versions.filter(status=ProgramVersion.Status.DRAFT).exists():
        raise ProgramError("this program already has a draft version", code="draft_exists")
    number = (program.versions.aggregate(m=Max("number"))["m"] or 0) + 1
    draft = ProgramVersion.objects.create(
        program=program,
        number=number,
        framework_version=source.framework_version,
        source_version=source,
        created_by=actor,
    )
    ProgramTarget.objects.bulk_create(
        ProgramTarget(version=draft, organization_id=draft.organization_id, competency_id=t.competency_id)
        for t in source.targets.all()
    )
    copy_content(source, draft)
    record(
        "program_version.created",
        actor=actor,
        target=draft,
        payload={"program_id": program.pk, "number": number, "from": source.number},
    )
    return draft


def copy_content(source: ProgramVersion, draft: ProgramVersion) -> None:
    """Copies the tree, blocks and alignment links; nodes level by level so every parent exists first."""
    node_ids: dict[int, int] = {}
    nodes = list(source.nodes.order_by("level", "order", "pk"))
    for level in sorted({n.level for n in nodes}):
        batch = [n for n in nodes if n.level == level]
        created = Node.objects.bulk_create(
            Node(
                version=draft,
                organization_id=draft.organization_id,
                node_key=n.node_key,
                parent_id=node_ids[n.parent_id] if n.parent_id else None,
                level=n.level,
                order=n.order,
                title=n.title,
                deleted=n.deleted,
            )
            for n in batch
        )
        node_ids.update({old.pk: new.pk for old, new in zip(batch, created, strict=True)})
    blocks = list(source.blocks.all())
    created_blocks = Block.objects.bulk_create(
        Block(
            version=draft,
            organization_id=draft.organization_id,
            node_id=node_ids[b.node_id],
            block_key=b.block_key,
            type=b.type,
            content=b.content,
            content_hash=b.content_hash,
            order=b.order,
            deleted=b.deleted,
        )
        for b in blocks
    )
    block_ids = {old.pk: new.pk for old, new in zip(blocks, created_blocks, strict=True)}
    AlignmentLink.objects.bulk_create(
        AlignmentLink(
            version=draft,
            organization_id=draft.organization_id,
            kind=link.kind,
            source_id=block_ids[link.source_id],
            target_block_id=block_ids[link.target_block_id] if link.target_block_id else None,
            target_competency_id=link.target_competency_id,
            created_by_id=link.created_by_id,
        )
        for link in source.alignment_links.all()
    )
