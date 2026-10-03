from django.db import transaction
from django.db.models import Max

from apps.accounts.models import Membership, Role
from apps.audit.services import record
from apps.core.locking import VersionLocked

from . import content as block_content
from .copying import create_draft_copy
from .errors import ProgramError
from .models import AlignmentLink, Block, Node, Program, ProgramCollaborator, ProgramTarget, ProgramVersion

EDITING_ROLES = {Role.ADMIN, Role.AUTHOR}
S = ProgramVersion.Status

__all__ = ["ProgramError", "can_edit", "can_manage", "create_program", "set_targets", "start_new_version"]


def _validate_targets(framework_version, target_ids) -> list[int]:
    ids = list(dict.fromkeys(int(i) for i in target_ids))
    found = set(framework_version.competencies.filter(pk__in=ids).values_list("pk", flat=True))
    if len(found) != len(ids):
        raise ProgramError(
            "every target must be a competency of the program's framework version", code="target_outside_framework"
        )
    return ids


@transaction.atomic
def create_program(*, title, target_role, owner, template_version, framework_version, target_ids) -> Program:
    if template_version.status != "published":
        raise ProgramError("choose a published version of the structure template", code="template_not_published")
    if framework_version.status != "published":
        raise ProgramError("choose a published version of the competency framework", code="framework_not_published")
    ids = _validate_targets(framework_version, target_ids)
    program = Program.objects.create(
        title=title, target_role=target_role, owner=owner, template_version=template_version
    )
    ProgramCollaborator.objects.create(program=program, user=owner, added_by=owner)
    version = ProgramVersion.objects.create(
        program=program, number=1, framework_version=framework_version, created_by=owner
    )
    for competency_id in ids:
        ProgramTarget.objects.create(version=version, competency_id=competency_id)
    record("program.created", actor=owner, target=program, payload={"title": title, "targets": ids})
    return program


@transaction.atomic
def set_targets(version: ProgramVersion, target_ids, *, actor) -> ProgramVersion:
    version = ProgramVersion.objects.select_for_update().get(pk=version.pk)
    if not version.is_editable:
        raise VersionLocked()
    ids = _validate_targets(version.framework_version, target_ids)
    ProgramTarget.objects.filter(version=version).delete()
    for competency_id in ids:
        ProgramTarget.objects.create(version=version, competency_id=competency_id)
    record("program_version.targets_changed", actor=actor, target=version, payload={"targets": ids})
    return version


def can_edit(program: Program, user, role: str) -> bool:
    return role in EDITING_ROLES and program.collaborators.filter(user=user).exists()


def can_manage(program: Program, user, role: str) -> bool:
    return role == Role.ADMIN or program.owner_id == user.pk


@transaction.atomic
def add_collaborator(program: Program, user, *, actor) -> ProgramCollaborator:
    membership = Membership.objects.filter(user=user).first()
    if membership is None or membership.role not in EDITING_ROLES:
        raise ProgramError(
            "only authors and admins of this organization can edit programs", code="collaborator_not_eligible"
        )
    if program.collaborators.filter(user=user).exists():
        raise ProgramError("this person already edits this program", code="collaborator_exists")
    collaborator = ProgramCollaborator.objects.create(program=program, user=user, added_by=actor)
    record("program.collaborator_added", actor=actor, target=program, payload={"user": user.email})
    return collaborator


@transaction.atomic
def remove_collaborator(collaborator: ProgramCollaborator, *, actor) -> None:
    if collaborator.user_id == collaborator.program.owner_id:
        raise ProgramError("the owner always edits the program", code="owner_is_collaborator")
    record(
        "program.collaborator_removed",
        actor=actor,
        target=collaborator.program,
        payload={"user": collaborator.user.email},
    )
    collaborator.delete()


@transaction.atomic
def start_new_version(program: Program, *, actor) -> ProgramVersion:
    """A new draft after approval (or cancellation). Returned and withdrawn versions get one automatically."""
    program = Program.objects.select_for_update().get(pk=program.pk)
    versions = program.versions.order_by("-number")
    if versions.filter(status__in=[S.DRAFT, S.SUBMITTED, S.IN_STAGE]).exists():
        raise ProgramError("finish or withdraw the current version first", code="new_version_not_allowed")
    source = versions.filter(status__in=[S.APPROVED, S.EXPORTED]).first() or versions.first()
    draft = create_draft_copy(source, actor=actor)
    program.status = Program.Status.DRAFT
    program.save(update_fields=["status"])
    return draft


# --- Tree and blocks (task 2.5) ---------------------------------------------------------------


def _editable(version: ProgramVersion) -> ProgramVersion:
    """A draft whose content may still be written through the REST API."""
    from apps.collab.models import DraftDocument

    version = ProgramVersion.objects.select_for_update().get(pk=version.pk)
    if not version.is_editable:
        raise VersionLocked()
    if DraftDocument.objects.filter(version=version).exists():
        raise ProgramError("this draft is edited live; change it in the editor", code="draft_is_live")
    return version


def _level_count(version: ProgramVersion) -> int:
    return version.program.template_version.levels.count()


def _next_order(queryset) -> int:
    return (queryset.aggregate(m=Max("order"))["m"] or 0) + 1


def _subtree(node: Node) -> list[Node]:
    found, frontier = [], [node]
    while frontier:
        current = frontier.pop()
        found.append(current)
        frontier.extend(Node.objects.filter(parent=current))
    return found


@transaction.atomic
def add_node(
    version: ProgramVersion, *, title: str, actor, parent: Node | None = None, order: int | None = None
) -> Node:
    version = _editable(version)
    if parent is not None and parent.version_id != version.pk:
        raise ProgramError("the parent must belong to the same version", code="node_parent_invalid")
    level = 0 if parent is None else parent.level + 1
    if level >= _level_count(version):
        raise ProgramError("the structure template has no level this deep", code="node_level_exceeds_template")
    siblings = Node.objects.filter(version=version, parent=parent)
    node = Node.objects.create(
        version=version,
        parent=parent,
        level=level,
        order=order if order is not None else _next_order(siblings),
        title=title.strip(),
    )
    record(
        "program_node.added", actor=actor, target=version, payload={"node_key": str(node.node_key), "title": node.title}
    )
    return node


@transaction.atomic
def update_node(node: Node, *, title: str, actor) -> Node:
    _editable(node.version)
    node.title = title.strip()
    node.save()
    return node


@transaction.atomic
def move_node(node: Node, *, parent: Node | None, order: int, actor) -> Node:
    version = _editable(node.version)
    if parent is not None and parent.version_id != version.pk:
        raise ProgramError("the parent must belong to the same version", code="node_parent_invalid")
    subtree = _subtree(node)
    if parent is not None and parent.pk in {n.pk for n in subtree}:
        raise ProgramError("a node cannot move under itself", code="node_move_cycle")
    new_level = 0 if parent is None else parent.level + 1
    shift = new_level - node.level
    if max(n.level for n in subtree) + shift >= _level_count(version):
        raise ProgramError("the moved branch would be deeper than the template", code="node_level_exceeds_template")
    for member in subtree:
        member.level += shift
        if member.pk == node.pk:
            member.parent = parent
            member.order = order
        member.save()
    record("program_node.moved", actor=actor, target=version, payload={"node_key": str(node.node_key)})
    node.refresh_from_db()
    return node


@transaction.atomic
def soft_delete_node(node: Node, *, actor) -> Node:
    _editable(node.version)
    node.deleted = True
    node.save()
    record("program_node.deleted", actor=actor, target=node.version, payload={"node_key": str(node.node_key)})
    return node


@transaction.atomic
def restore_node(node: Node, *, actor) -> Node:
    _editable(node.version)
    node.deleted = False
    node.save()
    record("program_node.restored", actor=actor, target=node.version, payload={"node_key": str(node.node_key)})
    return node


@transaction.atomic
def add_block(
    version: ProgramVersion, *, node: Node, type: str, actor, content=None, order: int | None = None
) -> Block:
    version = _editable(version)
    if node.version_id != version.pk:
        raise ProgramError("the node must belong to the same version", code="block_node_invalid")
    if type not in Block.Type.values:
        raise ProgramError("unknown block type", code="block_type_invalid")
    body = block_content.validate(content if content is not None else block_content.EMPTY_DOC)
    block = Block.objects.create(
        version=version,
        node=node,
        type=type,
        content=body,
        content_hash=block_content.content_hash(body),
        order=order if order is not None else _next_order(Block.objects.filter(version=version, node=node)),
    )
    record(
        "program_block.added", actor=actor, target=version, payload={"block_key": str(block.block_key), "type": type}
    )
    return block


@transaction.atomic
def update_block(
    block: Block, *, actor, content=None, type: str | None = None, node: Node | None = None, order: int | None = None
) -> Block:
    version = _editable(block.version)
    if content is not None:
        block.content = block_content.validate(content)
        block.content_hash = block_content.content_hash(block.content)
    if type is not None:
        if type not in Block.Type.values:
            raise ProgramError("unknown block type", code="block_type_invalid")
        block.type = type
    if node is not None:
        if node.version_id != version.pk:
            raise ProgramError("the node must belong to the same version", code="block_node_invalid")
        block.node = node
    if order is not None:
        block.order = order
    block.save()
    return block


@transaction.atomic
def soft_delete_block(block: Block, *, actor) -> Block:
    _editable(block.version)
    block.deleted = True
    block.save()
    record("program_block.deleted", actor=actor, target=block.version, payload={"block_key": str(block.block_key)})
    return block


@transaction.atomic
def restore_block(block: Block, *, actor) -> Block:
    _editable(block.version)
    block.deleted = False
    block.save()
    record("program_block.restored", actor=actor, target=block.version, payload={"block_key": str(block.block_key)})
    return block


# --- Alignment links (task 2.6) ------------------------------------------------------------------

K = AlignmentLink.Kind
T = Block.Type


def _invalid_link(reason: str):
    raise ProgramError(f"this alignment link is not valid: {reason}", code="link_invalid")


def _is_ancestor(candidate: Node, node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.pk == candidate.pk:
            return True
        current = current.parent
    return False


def link_problem(version: ProgramVersion, kind: str, source: Block, target: Block | None, competency) -> str | None:
    """Why a link would be invalid, or None. Shared by the REST service and live-document materialization."""
    blocks = [b for b in (source, target) if b is not None]
    if any(b.version_id != version.pk for b in blocks):
        return "both ends must belong to this version"
    if any(b.deleted for b in blocks):
        return "deleted blocks cannot be linked"
    if kind == K.OBJECTIVE_COMPETENCY:
        if source.type != T.OBJECTIVE or competency is None or target is not None:
            return "an objective links to a competency"
        if competency.version_id != version.framework_version_id:
            return "the competency must belong to this version's framework"
    elif kind == K.ASSESSMENT_OBJECTIVE:
        if source.type != T.ASSESSMENT or target is None or target.type != T.OBJECTIVE or competency is not None:
            return "an assessment links to an objective"
    elif kind == K.OBJECTIVE_PARENT:
        if source.type != T.OBJECTIVE or target is None or target.type != T.OBJECTIVE or competency is not None:
            return "an objective links to a higher objective"
        if not _is_ancestor(target.node, source.node):
            return "the higher objective must sit on an ancestor of the objective's node"
    else:
        return "unknown kind"
    return None


@transaction.atomic
def link(version: ProgramVersion, *, kind: str, source: Block, actor, target: Block | None = None, competency=None):
    version = _editable(version)
    problem = link_problem(version, kind, source, target, competency)
    if problem:
        _invalid_link(problem)
    if kind == K.OBJECTIVE_COMPETENCY:
        exists = AlignmentLink.objects.filter(version=version, kind=kind, source=source, target_competency=competency)
    else:
        exists = AlignmentLink.objects.filter(version=version, kind=kind, source=source, target_block=target)
    if exists.exists():
        raise ProgramError("this link already exists", code="link_exists")
    created = AlignmentLink.objects.create(
        version=version, kind=kind, source=source, target_block=target, target_competency=competency, created_by=actor
    )
    record(
        "alignment_link.added",
        actor=actor,
        target=version,
        payload={
            "kind": kind,
            "source": str(source.block_key),
            "target": str(target.block_key) if target else None,
            "competency": competency.code if competency else None,
        },
    )
    return created


@transaction.atomic
def unlink(alignment_link: AlignmentLink, *, actor) -> None:
    _editable(alignment_link.version)
    record(
        "alignment_link.removed",
        actor=actor,
        target=alignment_link.version,
        payload={"kind": alignment_link.kind, "source": str(alignment_link.source.block_key)},
    )
    alignment_link.delete()
