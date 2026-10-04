"""The rules around a submission (spec 6.2, tasks 5.4 and 5.5): the pre-submit check on critical findings, open
must_fix comments blocking final approval, a return needing an open comment, and the must_fix comments resolved
since the return shown to the reviewer on resubmission."""

import pytest

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.comments import services as comments
from apps.comments.models import Comment
from apps.core.errors import Conflict
from apps.programs import services as programs
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.quality import services as quality
from apps.quality.models import QualityReport
from apps.tenancy.context import organization_context
from apps.workflows import services
from apps.workflows.models import StageTask, WorkflowInstance
from apps.workflows.serializers import WorkflowInstanceSerializer

from .factories import one_stage_template

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        admin = member("admin@example.com", Role.ADMIN)
        author = member("author@example.com", Role.AUTHOR)
        reviewer = member("reviewer@example.com", Role.REVIEWER)
        one_stage_template(admin)
        # Two target competencies that no assessment reaches: two critical findings (D36).
        version = program(author).versions.get()
        node = programs.add_node(version, title="الوحدة", actor=author)
        yield {"org": org, "admin": admin, "author": author, "reviewer": reviewer, "version": version, "node": node}


def submit(world, version=None, reason=""):
    version = version or world["version"]
    return services.submit(version, actor=world["author"], role=Role.AUTHOR, reason=reason)


def comment(world, version, category, user=None):
    return comments.create_comment(
        program=version.program,
        version=version,
        author=user or world["reviewer"],
        body="أكمل التقويم",
        category=category,
        node_key=version.nodes.get(title="الوحدة").node_key,
    )


def decide(world, decision, note="", version=None):
    task = StageTask.objects.get(instance__version=version or world["version"], closed_at__isnull=True)
    services.claim(task, actor=world["reviewer"], role=Role.REVIEWER)
    return services.decide(task, actor=world["reviewer"], role=Role.REVIEWER, decision=decision, note=note)


def code(excinfo):
    return excinfo.value.get_codes()


# --- Pre-submit check (task 5.4) ----------------------------------------------------------------------------


def test_critical_findings_need_a_written_reason_by_default(world):
    with pytest.raises(Conflict) as refused:
        submit(world)
    assert code(refused) == "critical_findings_reason_required"
    world["version"].refresh_from_db()
    assert world["version"].status == S.DRAFT

    version = submit(world, reason="  التقويم في الوحدة التالية  ")
    assert version.status == S.IN_STAGE
    kept = WorkflowInstance.objects.get(version=version).pre_submit
    assert kept["reason"] == "التقويم في الوحدة التالية"
    assert [f["kind"] for f in kept["critical"]] == ["competency_not_assessed", "competency_not_assessed"]
    submitted = AuditLog.objects.filter(event="program_version.transition", payload__to=S.SUBMITTED).get()
    assert submitted.payload["pre_submit"] == kept


def test_an_organization_may_block_submission_on_critical_findings(world):
    world["org"].pre_submit_critical_behavior = Organization.PreSubmitBehavior.BLOCK
    world["org"].save()
    with pytest.raises(Conflict) as blocked:
        submit(world, reason="مقبول")
    assert code(blocked) == "critical_findings_block"


def test_without_critical_findings_no_reason_is_asked_or_kept(world):
    version = program(world["author"], title="بلا أهداف مستهدفة", targets=[]).versions.get()
    submitted = submit(world, version, reason="غير مطلوب")
    assert WorkflowInstance.objects.get(version=submitted).pre_submit == {}


def test_a_dismissed_critical_finding_does_not_count(world, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=False):
        run = quality.request_run(world["version"], QualityReport.Run.LIGHT)
    quality.execute_run(run.pk, str(run.run_id))
    report = QualityReport.objects.get(version=world["version"])
    for finding in report.findings.filter(severity="critical"):
        quality.dismiss(finding, reason="يُقوَّم في برنامج آخر", actor=world["author"], role=Role.AUTHOR)
    assert submit(world).status == S.IN_STAGE


def test_the_check_reads_the_rows_at_submission_not_an_old_report(world, django_capture_on_commit_callbacks):
    # The report was run when nothing was targeted; the targets came later and the rules see them at submission.
    version = program(world["author"], title="ثان", targets=[]).versions.get()
    with django_capture_on_commit_callbacks(execute=False):
        run = quality.request_run(version, QualityReport.Run.LIGHT)
    quality.execute_run(run.pk, str(run.run_id))
    competencies = list(version.framework_version.competencies.values_list("pk", flat=True)[:1])
    programs.set_targets(version, competencies, actor=world["author"])
    with pytest.raises(Conflict) as refused:
        submit(world, version)
    assert code(refused) == "critical_findings_reason_required"


# --- Comments (task 5.5) ------------------------------------------------------------------------------------


def test_an_open_must_fix_comment_blocks_final_approval_but_not_a_suggestion(world):
    submit(world, reason="سبب")
    must_fix = comment(world, world["version"], Comment.Category.MUST_FIX)
    comment(world, world["version"], Comment.Category.SUGGESTION)
    with pytest.raises(Conflict) as blocked:
        decide(world, "approve")
    assert code(blocked) == "open_must_fix"
    with organization_context(world["org"]):
        Comment.objects.filter(pk=must_fix.pk).update(status=Comment.Status.RESOLVED)
    assert decide(world, "approve").status == S.APPROVED


def test_must_fix_blocks_only_the_final_approval(world):
    services.save_template(
        None,
        actor=world["admin"],
        name="مرحلتان",
        is_default=True,
        stages=[
            {"name": "أولى", "assignee_role": "reviewer", "due_work_days": 1},
            {"name": "نهائية", "assignee_role": "reviewer", "due_work_days": 1},
        ],
    )
    submit(world, reason="سبب")
    comment(world, world["version"], Comment.Category.MUST_FIX)
    assert decide(world, "approve").current_stage == 2
    with pytest.raises(Conflict):
        decide(world, "approve")


def test_a_return_needs_an_open_comment_on_the_version(world):
    submit(world, reason="سبب")
    with pytest.raises(Conflict) as bare:
        decide(world, "return", note="أعد")
    assert code(bare) == "return_comment_required"
    comment(world, world["version"], Comment.Category.SUGGESTION)
    assert decide(world, "return", note="أعد").status == S.RETURNED


def test_the_reviewer_sees_the_must_fix_comments_resolved_since_the_return(world):
    submit(world, reason="سبب")
    fixed = comment(world, world["version"], Comment.Category.MUST_FIX)
    comment(world, world["version"], Comment.Category.SUGGESTION)
    returned = decide(world, "return", note="أكمل")
    draft = returned.program.versions.get(status=S.DRAFT)
    comments.resolve(fixed, actor=world["author"], role=Role.AUTHOR)
    resubmitted = submit(world, draft, reason="سبب")

    instance = WorkflowInstance.objects.get(version=resubmitted)
    listed = WorkflowInstanceSerializer(instance).data["resolved_must_fix"]
    assert [c["id"] for c in listed] == [fixed.pk]
    assert listed[0]["resolved_by"]["email"] == "author@example.com"
    # The reviewer reopens it: it blocks approval again, and leaves the list.
    comments.reopen(Comment.objects.get(pk=fixed.pk), actor=world["reviewer"], role=Role.REVIEWER)
    assert WorkflowInstanceSerializer(instance).data["resolved_must_fix"] == []
    with pytest.raises(Conflict) as blocked:
        decide(world, "approve", version=resubmitted)
    assert code(blocked) == "open_must_fix"
