"""Every change to frameworks goes through these functions, which also write the audit log."""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import Conflict
from apps.core.locking import lifecycle_write

from .models import Competency, CompetencyFramework, FrameworkVersion


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
