from django.db import transaction

from apps.accounts.models import Membership, Role
from apps.audit.services import record
from apps.core.locking import VersionLocked

from .copying import create_draft_copy
from .errors import ProgramError
from .models import Program, ProgramCollaborator, ProgramTarget, ProgramVersion

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
