import itertools

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.core.locking import VersionLocked, lifecycle_write
from apps.programs import lifecycle, services
from apps.programs.models import ProgramTarget, ProgramVersion
from apps.tenancy.context import organization_context

from .factories import member, program, published_framework

pytestmark = pytest.mark.django_db

S = ProgramVersion.Status
ALLOWED = {
    (S.DRAFT, S.SUBMITTED),
    (S.DRAFT, S.CANCELLED),
    (S.SUBMITTED, S.IN_STAGE),
    (S.SUBMITTED, S.WITHDRAWN),
    (S.SUBMITTED, S.CANCELLED),
    (S.IN_STAGE, S.IN_STAGE),
    (S.IN_STAGE, S.APPROVED),
    (S.IN_STAGE, S.RETURNED),
    (S.IN_STAGE, S.WITHDRAWN),
    (S.IN_STAGE, S.CANCELLED),
    (S.APPROVED, S.EXPORTED),
}


@pytest.fixture
def ctx():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        yield org, owner


def version_in(status, owner):
    """A version forced into `status`, bypassing the transition table, to test every starting point."""
    version = program(owner).versions.get()
    with lifecycle_write():
        version.status = status
        version.current_stage = 1 if status == S.IN_STAGE else None
        version.save()
    return version


def stage_for(version, target):
    return {"stage": (version.current_stage or 0) + 1} if target == S.IN_STAGE else {}


def test_the_transition_table_matches_the_spec():
    assert lifecycle.ALLOWED == ALLOWED


@pytest.mark.parametrize("source,target", sorted(itertools.product(S.values, S.values)))
def test_every_transition_is_allowed_or_refused(ctx, source, target):
    _, owner = ctx
    version = version_in(source, owner)
    if (source, target) in ALLOWED:
        lifecycle.transition(version, target, actor=owner, **stage_for(version, target))
        version.refresh_from_db()
        assert version.status == target
        entry = AuditLog.objects.filter(event="program_version.transition").last()
        assert entry.payload["from"] == source and entry.payload["to"] == target
    else:
        with pytest.raises(lifecycle.TransitionRefused):
            lifecycle.transition(version, target, actor=owner, **stage_for(version, target))
        version.refresh_from_db()
        assert version.status == source


def test_status_cannot_be_changed_outside_the_transition_point(ctx):
    _, owner = ctx
    version = program(owner).versions.get()
    lifecycle.transition(version, S.SUBMITTED, actor=owner)
    version.status = S.DRAFT
    with pytest.raises(VersionLocked):
        version.save()
    with pytest.raises(VersionLocked):
        ProgramVersion.objects.filter(pk=version.pk).update(status=S.DRAFT)


def test_program_status_follows_its_versions(ctx):
    _, owner = ctx
    prog = program(owner)
    version = prog.versions.get()
    assert prog.status == "draft"
    lifecycle.transition(version, S.SUBMITTED, actor=owner)
    prog.refresh_from_db()
    assert prog.status == "in_review"
    lifecycle.transition(version, S.IN_STAGE, actor=owner, stage=1)
    lifecycle.transition(version, S.APPROVED, actor=owner)
    prog.refresh_from_db()
    assert prog.status == "approved"
    version.refresh_from_db()
    assert version.approved_by == owner and version.approved_at is not None


def test_returning_or_withdrawing_creates_a_new_draft_copy(ctx):
    _, owner = ctx
    prog = program(owner)
    v1 = prog.versions.get()
    lifecycle.transition(v1, S.SUBMITTED, actor=owner)
    lifecycle.transition(v1, S.WITHDRAWN, actor=owner)
    v2 = prog.versions.get(number=2)
    assert v2.status == S.DRAFT and v2.source_version == v1
    assert set(v2.targets.values_list("competency_id", flat=True)) == set(
        v1.targets.values_list("competency_id", flat=True)
    )
    prog.refresh_from_db()
    assert prog.status == "draft"

    lifecycle.transition(v2, S.SUBMITTED, actor=owner)
    lifecycle.transition(v2, S.IN_STAGE, actor=owner, stage=1)
    lifecycle.transition(v2, S.RETURNED, actor=owner)
    assert prog.versions.get(number=3).status == S.DRAFT


def test_a_new_version_after_approval_and_only_one_draft(ctx):
    _, owner = ctx
    prog = program(owner)
    with pytest.raises(services.ProgramError):
        services.start_new_version(prog, actor=owner)
    v1 = prog.versions.get()
    for target in (S.SUBMITTED, S.IN_STAGE, S.APPROVED):
        lifecycle.transition(v1, target, actor=owner, **({"stage": 1} if target == S.IN_STAGE else {}))
    v2 = services.start_new_version(prog, actor=owner)
    assert (v2.number, v2.status, v2.source_version_id) == (2, S.DRAFT, v1.pk)


def test_locked_versions_reject_target_changes_everywhere(ctx):
    _, owner = ctx
    version = program(owner).versions.get()
    target = version.targets.first()
    lifecycle.transition(version, S.SUBMITTED, actor=owner)
    with pytest.raises(VersionLocked):
        services.set_targets(version, [], actor=owner)
    with pytest.raises(VersionLocked):
        target.delete()
    with pytest.raises(VersionLocked):
        ProgramTarget.objects.filter(version=version).delete()
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM programs_programtarget WHERE id = %s", [target.pk])


def test_program_needs_published_template_and_framework_and_targets_from_that_framework(ctx):
    _, owner = ctx
    from apps.competencies import services as competency_services
    from apps.structures import services as structure_services

    from .factories import FOUR_LEVELS

    draft_template = structure_services.create_template(name="d", actor=owner, levels=FOUR_LEVELS).versions.get()
    with pytest.raises(services.ProgramError) as excinfo:
        program(owner, template=draft_template)
    assert excinfo.value.get_codes() == "template_not_published"

    draft_framework = competency_services.create_framework(name="d", actor=owner).versions.get()
    with pytest.raises(services.ProgramError) as excinfo:
        program(owner, framework=draft_framework, targets=[])
    assert excinfo.value.get_codes() == "framework_not_published"

    other = published_framework(owner, codes=("Z-1",))
    with pytest.raises(services.ProgramError) as excinfo:
        program(owner, targets=[other.competencies.get().pk])
    assert excinfo.value.get_codes() == "target_outside_framework"


def test_owner_is_a_collaborator_and_collaborators_must_be_active_members(ctx):
    _, owner = ctx
    prog = program(owner)
    assert list(prog.collaborators.values_list("user__email", flat=True)) == ["owner@example.com"]
    colleague = member("colleague@example.com", Role.AUTHOR)
    services.add_collaborator(prog, colleague, actor=owner)
    pending = member("pending@example.com", Role.PENDING)
    with pytest.raises(services.ProgramError) as excinfo:
        services.add_collaborator(prog, pending, actor=owner)
    assert excinfo.value.get_codes() == "collaborator_not_eligible"
    assert services.can_edit(prog, colleague, Role.AUTHOR)
    reviewer = member("reviewer@example.com", Role.REVIEWER)
    assert not services.can_edit(prog, reviewer, Role.REVIEWER)


def test_stages_advance_one_at_a_time(ctx):
    _, owner = ctx
    version = program(owner).versions.get()
    lifecycle.transition(version, S.SUBMITTED, actor=owner)
    with pytest.raises(lifecycle.TransitionRefused):
        lifecycle.transition(version, S.IN_STAGE, actor=owner, stage=0)
    lifecycle.transition(version, S.IN_STAGE, actor=owner, stage=1)
    with pytest.raises(lifecycle.TransitionRefused):
        lifecycle.transition(version, S.IN_STAGE, actor=owner, stage=3)
    lifecycle.transition(version, S.IN_STAGE, actor=owner, stage=2)
    version.refresh_from_db()
    assert version.current_stage == 2


def test_a_submission_may_enter_a_later_stage_but_a_stage_only_leads_to_the_next(ctx):
    _, owner = ctx
    submitted = version_in(S.SUBMITTED, owner)
    with pytest.raises(lifecycle.TransitionRefused):
        lifecycle.transition(submitted, S.IN_STAGE, actor=owner)
    assert lifecycle.transition(submitted, S.IN_STAGE, actor=owner, stage=3).current_stage == 3
    with pytest.raises(lifecycle.TransitionRefused):
        lifecycle.transition(submitted, S.IN_STAGE, actor=owner, stage=5)
    assert lifecycle.transition(submitted, S.IN_STAGE, actor=owner, stage=4).current_stage == 4


def test_a_check_runs_under_the_lock_and_can_refuse(ctx):
    _, owner = ctx
    version = program(owner).versions.get()
    seen = []

    def check(locked):
        seen.append(locked.status)
        raise lifecycle.TransitionRefused("not now", code="not_now")

    with pytest.raises(lifecycle.TransitionRefused):
        lifecycle.transition(version, S.SUBMITTED, actor=owner, check=check)
    version.refresh_from_db()
    assert seen == [S.DRAFT] and version.status == S.DRAFT
    assert not AuditLog.objects.filter(event="program_version.transition").exists()


def test_then_runs_after_the_change_in_the_same_transaction(ctx):
    _, owner = ctx
    version = program(owner).versions.get()

    def then(changed):
        assert changed.status == S.SUBMITTED
        assert AuditLog.objects.filter(event="program_version.transition").count() == 1
        raise RuntimeError("the follow-up failed")

    with pytest.raises(RuntimeError):
        lifecycle.transition(version, S.SUBMITTED, actor=owner, then=then)
    version.refresh_from_db()
    assert version.status == S.DRAFT  # rolled back with it
    assert not AuditLog.objects.filter(event="program_version.transition").exists()
