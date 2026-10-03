"""Quality reports: runs follow the content, dismissals need a reason and follow the finding, the report of
a submitted version is final (task 4.3)."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.collab.materialization import apply_rows, rows_from_version
from apps.programs import lifecycle, services
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.quality import services as quality
from apps.quality.models import Finding, QualityReport, ReportLocked
from apps.quality.rules import program as program_rules
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


def doc(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


@pytest.fixture
def world(django_capture_on_commit_callbacks):
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org), django_capture_on_commit_callbacks(execute=True):
        owner = member("author@example.com", Role.AUTHOR)
        member("reviewer@example.com", Role.REVIEWER)
        prog = program(owner)
        version = prog.versions.get()
        root = services.add_node(version, title="البرنامج", actor=owner)
        lesson = services.add_node(version, title="الدرس الأول", parent=root, actor=owner)
        objective = services.add_block(
            version, node=lesson, type="objective", actor=owner, content=doc("أن يفهم المتدرب أهمية السلامة")
        )
    return {
        "org": org,
        "owner": owner,
        "program": prog,
        "version": version,
        "root": root,
        "lesson": lesson,
        "objective": objective,
    }


def report_of(w):
    with organization_context(w["org"]):
        return QualityReport.objects.get(version=w["version"])


def findings(w, **where):
    with organization_context(w["org"]):
        return list(Finding.objects.filter(report__version=w["version"], **where))


def test_a_change_to_a_draft_runs_the_rules(world):
    report = report_of(world)
    assert (report.status, report.last_run, report.rules_version) == ("complete", "light", program_rules.RULES_VERSION)
    kinds = sorted(f.kind for f in findings(world))
    assert kinds.count("competency_not_assessed") == 2
    assert {"objective_unmeasurable", "objective_not_aligned", "node_missing_assessment"} <= set(kinds)
    assert report.counts == {"critical": 2, "warning": 3, "info": 3}


def test_the_report_api_lists_findings_objectives_and_the_roll_up(world):
    body = login("reviewer@example.com").get(f"/api/program-versions/{world['version'].pk}/quality/").json()
    assert body["status"] == "complete"
    critical = [f for f in body["findings"] if f["severity"] == "critical"]
    assert len(critical) == 2 and all(f["competency"]["code"].startswith("C-") for f in critical)
    [objective] = body["objectives"]
    assert objective["rule"] == {"level_id": 2, "level": "فهم", "domain": "cognitive", "confidence": "high"}
    assert objective["ai"] is None
    root, lesson = str(world["root"].node_key), str(world["lesson"].node_key)
    assert body["rollup"][lesson] == {"critical": 0, "warning": 3, "info": 3}
    assert body["rollup"][root] == {"critical": 2, "warning": 3, "info": 3}


def test_a_version_without_a_report_says_so(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]):
        QualityReport.objects.filter(version=world["version"]).delete()
    response = login("author@example.com").get(f"/api/program-versions/{world['version'].pk}/quality/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "report_not_found"


def test_a_superseded_run_writes_nothing(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]):
        with django_capture_on_commit_callbacks(execute=False):
            first = str(quality.request_run(world["version"], "light").run_id)
            second = str(quality.request_run(world["version"], "full").run_id)
            services.update_block(
                world["objective"], content=doc("أن يذكر المتدرب خطوات الإخلاء"), actor=world["owner"]
            )
    quality.execute_run(report_of(world).pk, first)
    assert report_of(world).status == "running"
    quality.execute_run(report_of(world).pk, second)
    report = report_of(world)
    assert (report.status, report.last_run) == ("complete", "full")
    assert not [f for f in findings(world) if f.kind == "objective_unmeasurable"]


def test_dismissal_needs_a_reason_is_audited_and_survives_reruns(world, django_capture_on_commit_callbacks):
    author = login("author@example.com")
    [vague] = findings(world, kind="objective_unmeasurable")
    refused = author.post(f"/api/findings/{vague.pk}/dismiss/", {"reason": "  "}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "dismissal_reason_required"
    reason = "الفهم هنا مقصود ويقاس في التقويم العملي"
    response = author.post(f"/api/findings/{vague.pk}/dismiss/", {"reason": reason}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["dismissal"]["reason"] == reason
    assert report_of(world).counts["warning"] == 2
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_node(world["lesson"], title="الدرس الأول: السلامة", actor=world["owner"])
    [again] = findings(world, kind="objective_unmeasurable")
    assert again.pk != vague.pk and again.dismissed_reason == reason
    assert report_of(world).counts["warning"] == 2
    assert author.post(f"/api/findings/{again.pk}/restore/", {}, format="json").json()["dismissal"] is None
    assert report_of(world).counts["warning"] == 3
    with organization_context(world["org"]):
        events = list(AuditLog.objects.filter(event__startswith="quality.").values_list("event", flat=True))
    assert events == ["quality.finding_dismissed", "quality.finding_restored"]


def test_only_the_programs_editors_dismiss(world):
    [vague] = findings(world, kind="objective_unmeasurable")
    response = login("reviewer@example.com").post(f"/api/findings/{vague.pk}/dismiss/", {"reason": "x"}, format="json")
    assert response.status_code == 403


def test_submission_writes_a_final_report_that_cannot_change(world, django_capture_on_commit_callbacks):
    [vague] = findings(world, kind="objective_unmeasurable")
    with organization_context(world["org"]):
        quality.dismiss(vague, reason="مقصود", actor=world["owner"], role=Role.AUTHOR)
        with django_capture_on_commit_callbacks(execute=True):
            lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    report = report_of(world)
    assert (report.status, report.last_run) == ("complete", "full")
    [kept] = findings(world, kind="objective_unmeasurable")
    assert kept.dismissed_reason == "مقصود"
    author = login("author@example.com")
    response = author.post(f"/api/findings/{kept.pk}/restore/", {}, format="json")
    assert response.status_code == 409 and response.json()["error"]["code"] == "report_locked"
    run = author.post(f"/api/program-versions/{world['version'].pk}/quality/run/", {}, format="json")
    assert run.status_code == 409 and run.json()["error"]["code"] == "report_locked"
    with organization_context(world["org"]):
        kept.dismissed_reason = "تغيير"
        with pytest.raises(ReportLocked):
            kept.save()
        report.counts = {}
        with pytest.raises(ReportLocked):
            report.save()
        with pytest.raises(ReportLocked):
            report.delete()


def test_cancelling_a_draft_runs_nothing(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        lifecycle.transition(world["version"], S.CANCELLED, actor=world["owner"])
    assert report_of(world).last_run == "light"


def test_the_next_draft_carries_dismissals_once(world, django_capture_on_commit_callbacks):
    owner = world["owner"]
    [vague] = findings(world, kind="objective_unmeasurable")
    with organization_context(world["org"]):
        quality.dismiss(vague, reason="مقصود", actor=owner, role=Role.AUTHOR)
        with django_capture_on_commit_callbacks(execute=True):
            lifecycle.transition(world["version"], S.SUBMITTED, actor=owner)
            lifecycle.transition(world["version"], S.IN_STAGE, actor=owner, stage=1)
            lifecycle.transition(world["version"], S.RETURNED, actor=owner)
        draft = world["program"].versions.get(status=S.DRAFT)
        block = draft.blocks.get(block_key=world["objective"].block_key)
        with django_capture_on_commit_callbacks(execute=True):
            services.update_block(block, content=doc("أن يفهم المتدرب أهمية السلامة."), actor=owner)
        [carried] = Finding.objects.filter(report__version=draft, kind="objective_unmeasurable")
        assert carried.dismissed_reason == "مقصود"
        quality.restore(carried, actor=owner, role=Role.AUTHOR)
        with django_capture_on_commit_callbacks(execute=True):
            services.update_block(block, content=doc("أن يفهم المتدرب أهمية السلامة"), actor=owner)
        [restored] = Finding.objects.filter(report__version=draft, kind="objective_unmeasurable")
        assert restored.dismissed_at is None


def test_a_failing_run_is_reported_and_alerted(world, monkeypatch, django_capture_on_commit_callbacks):
    alerts = []
    monkeypatch.setattr(quality.program_rules, "analyze", lambda snapshot: 1 / 0)
    monkeypatch.setattr(quality.sentry_sdk, "capture_exception", alerts.append)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        quality.request_run(world["version"], "full")
    report = report_of(world)
    assert report.status == "failed" and "division by zero" in report.error
    assert len(alerts) == 1


def test_live_materialization_triggers_a_light_run(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]):
        rows = rows_from_version(world["version"])
        rows["blocks"][0]["content"] = doc("أن يذكر المتدرب خطوات الإخلاء بدقة")
        with django_capture_on_commit_callbacks(execute=True):
            apply_rows(world["version"], rows, actor=world["owner"])
    with organization_context(world["org"]):
        objective = report_of(world).objectives.get()
    assert (objective.verb, objective.level) == ("يذكر", "تذكر")


def test_a_broker_outage_does_not_fail_the_change_that_asked_for_a_run(
    world, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.quality import tasks

    def down(*args, **kwargs):
        raise ConnectionError("broker unreachable")

    alerts = []
    monkeypatch.setattr(tasks.run_report, "apply_async", down)
    monkeypatch.setattr(quality.sentry_sdk, "capture_exception", alerts.append)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_node(world["lesson"], title="عنوان جديد", actor=world["owner"])
    assert report_of(world).status == "running"
    assert len(alerts) == 1
