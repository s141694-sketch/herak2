"""Every change to frameworks goes through these functions, which also write the audit log."""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import Conflict
from apps.core.locking import VersionLocked, lifecycle_write

from . import importing
from .models import Competency, CompetencyFramework, CompetencyImport, FrameworkVersion


class FrameworkError(Conflict):
    default_code = "framework_error"


@transaction.atomic
def create_framework(*, name: str, actor, description: str = "") -> CompetencyFramework:
    framework = CompetencyFramework.objects.create(name=name, description=description, created_by=actor)
    FrameworkVersion.objects.create(framework=framework, number=1, created_by=actor)
    record("competency_framework.created", actor=actor, target=framework, payload={"name": name})
    return framework


def add_competency(version: FrameworkVersion, **fields) -> Competency:
    if "order" not in fields:
        fields["order"] = (version.competencies.aggregate(m=Max("order"))["m"] or 0) + 1
    return Competency.objects.create(version=version, **fields)


@transaction.atomic
def publish_version(version: FrameworkVersion, *, actor) -> FrameworkVersion:
    version = FrameworkVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != FrameworkVersion.Status.DRAFT:
        raise FrameworkError("only a draft version can be published", code="framework_not_draft")
    if not version.competencies.exists():
        raise FrameworkError("a version needs at least one competency before publishing", code="framework_empty")
    version.status = FrameworkVersion.Status.PUBLISHED
    version.published_by = actor
    version.published_at = timezone.now()
    with lifecycle_write():
        version.save()
    record(
        "competency_framework.version_published",
        actor=actor,
        target=version,
        payload={"framework_id": version.framework_id, "number": version.number},
    )
    return version


@transaction.atomic
def new_version(framework: CompetencyFramework, *, actor) -> FrameworkVersion:
    """Starts a new draft from the latest published version, keeping every competency_key."""
    framework = CompetencyFramework.objects.select_for_update().get(pk=framework.pk)
    if framework.draft() is not None:
        raise FrameworkError("this framework already has a draft version", code="framework_draft_exists")
    source = framework.latest_published()
    number = (framework.versions.aggregate(m=Max("number"))["m"] or 0) + 1
    version = FrameworkVersion.objects.create(framework=framework, number=number, created_by=actor)
    if source is not None:
        Competency.objects.bulk_create(
            Competency(
                version=version,
                organization_id=version.organization_id,
                competency_key=c.competency_key,
                code=c.code,
                title=c.title,
                description=c.description,
                level=c.level,
                requirement=c.requirement,
                order=c.order,
            )
            for c in source.competencies.all()
        )
    record(
        "competency_framework.version_created",
        actor=actor,
        target=version,
        payload={"framework_id": framework.pk, "number": number, "from": source.number if source else None},
    )
    return version


def _existing_values(version: FrameworkVersion) -> dict[str, dict[str, str]]:
    return {c["code"]: {k: c[k] for k in importing.COLUMNS} for c in version.competencies.values(*importing.COLUMNS)}


def preview_import(version: FrameworkVersion, *, file_name: str, data: bytes, actor) -> CompetencyImport:
    if not version.is_editable:
        raise VersionLocked()
    rows = importing.validate(importing.parse(file_name, data), _existing_values(version))
    return CompetencyImport.objects.create(
        version=version,
        file_name=file_name[:255],
        rows=[{"row": r.row, "values": r.values, "errors": r.errors, "action": r.action} for r in rows],
        summary=importing.summarize(rows),
        uploaded_by=actor,
    )


@transaction.atomic
def confirm_import(batch: CompetencyImport, *, actor) -> CompetencyImport:
    batch = CompetencyImport.objects.select_for_update().get(pk=batch.pk)
    if batch.status != CompetencyImport.Status.PREVIEWED:
        raise FrameworkError("this import was already applied", code="import_not_pending")
    version = FrameworkVersion.objects.select_for_update().get(pk=batch.version_id)
    if not version.is_editable:
        raise VersionLocked()
    # Re-validate against the version as it is now: it may have changed since the preview.
    rows = [importing.ParsedRow(row=r["row"], values=dict(r["values"])) for r in batch.rows]
    rows = importing.validate(rows, _existing_values(version))
    summary = importing.summarize(rows)
    if summary["errors"]:
        raise FrameworkError("fix the rows with errors and upload the file again", code="import_has_errors")
    by_code = {c.code: c for c in version.competencies.all()}
    for row in rows:
        if row.action == "create":
            add_competency(version, **row.values)
        elif row.action == "update":
            competency = by_code[row.values["code"]]
            for column, value in row.values.items():
                setattr(competency, column, value)
            competency.save()
    batch.status = CompetencyImport.Status.APPLIED
    batch.summary = summary
    batch.applied_at = timezone.now()
    batch.save()
    record("competency_framework.imported", actor=actor, target=version, payload={"file": batch.file_name, **summary})
    return batch
