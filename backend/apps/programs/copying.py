"""Creating a new draft version as a copy of an existing one. Rows keep their stable keys."""

from django.db.models import Max

from apps.audit.services import record

from .errors import ProgramError
from .models import ProgramTarget, ProgramVersion


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
    """Copies the tree, blocks and alignment links. Filled in by tasks 2.5 and 2.6."""
