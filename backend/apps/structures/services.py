from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record
from apps.core.errors import Conflict
from apps.core.locking import VersionLocked, lifecycle_write

from .models import MAX_LEVELS, Level, StructureTemplate, TemplateVersion


class TemplateError(Conflict):
    default_code = "template_error"


def _clean_levels(levels: list[dict]) -> list[dict]:
    if not 1 <= len(levels) <= MAX_LEVELS:
        raise TemplateError(f"a template has between 1 and {MAX_LEVELS} levels", code="template_level_count")
    cleaned = []
    for level in levels:
        name_ar = str(level.get("name_ar", "")).strip()
        name_en = str(level.get("name_en", "")).strip()
        if not name_ar or not name_en:
            raise TemplateError("every level needs an Arabic and an English name", code="template_level_name_missing")
        cleaned.append({"name_ar": name_ar, "name_en": name_en})
    return cleaned


def _write_levels(version: TemplateVersion, levels: list[dict]) -> None:
    Level.objects.filter(version=version).delete()
    for depth, level in enumerate(levels):
        Level.objects.create(version=version, depth=depth, **level)


@transaction.atomic
def create_template(*, name: str, actor, levels: list[dict]) -> StructureTemplate:
    levels = _clean_levels(levels)
    template = StructureTemplate.objects.create(name=name, created_by=actor)
    version = TemplateVersion.objects.create(template=template, number=1, created_by=actor)
    _write_levels(version, levels)
    record("structure_template.created", actor=actor, target=template, payload={"name": name, "levels": levels})
    return template


@transaction.atomic
def set_levels(version: TemplateVersion, levels: list[dict], *, actor) -> TemplateVersion:
    version = TemplateVersion.objects.select_for_update().get(pk=version.pk)
    if not version.is_editable:
        raise VersionLocked()
    levels = _clean_levels(levels)
    _write_levels(version, levels)
    record("structure_template.levels_changed", actor=actor, target=version, payload={"levels": levels})
    return version


@transaction.atomic
def publish_version(version: TemplateVersion, *, actor) -> TemplateVersion:
    version = TemplateVersion.objects.select_for_update().get(pk=version.pk)
    if not version.is_editable:
        raise TemplateError("only a draft version can be published", code="template_not_draft")
    version.status = TemplateVersion.Status.PUBLISHED
    version.published_at = timezone.now()
    with lifecycle_write():
        version.save()
    record("structure_template.version_published", actor=actor, target=version, payload={"number": version.number})
    return version


@transaction.atomic
def new_version(template: StructureTemplate, *, actor) -> TemplateVersion:
    template = StructureTemplate.objects.select_for_update().get(pk=template.pk)
    if template.draft() is not None:
        raise TemplateError("this template already has a draft version", code="template_draft_exists")
    source = template.latest_published()
    number = (template.versions.aggregate(m=Max("number"))["m"] or 0) + 1
    version = TemplateVersion.objects.create(template=template, number=number, created_by=actor)
    if source is not None:
        _write_levels(version, list(source.levels.values("name_ar", "name_en")))
    record("structure_template.version_created", actor=actor, target=version, payload={"number": number})
    return version
