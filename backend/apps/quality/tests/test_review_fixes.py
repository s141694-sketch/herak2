"""Findings of the independent review of phase 4's quality engine, each reproduced here first."""

import threading

import pytest
from django.db import close_old_connections, connection, transaction

from apps.accounts.models import Role
from apps.programs import lifecycle, services
from apps.programs.models import ProgramVersion
from apps.quality import services as quality
from apps.quality.models import Finding, QualityReport
from apps.tenancy.context import organization_context

from .test_ai_layer import AMBIGUOUS, ai_findings
from .test_ai_layer import world as ai_world  # noqa: F401 - fixture
from .test_reports import doc, findings, login, report_of, world  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


def test_two_links_from_one_block_to_deleted_blocks_are_two_findings_and_the_run_completes(
    world,  # noqa: F811
    django_capture_on_commit_callbacks,  # noqa: F811
):
    owner, version = world["owner"], world["version"]
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        first = services.add_block(
            version, node=world["lesson"], type="objective", actor=owner, content=doc("أن يذكر المتدرب أ")
        )
        second = services.add_block(
            version, node=world["lesson"], type="objective", actor=owner, content=doc("أن يذكر المتدرب ب")
        )
        test = services.add_block(version, node=world["lesson"], type="assessment", actor=owner, content=doc("اختبار"))
        services.link(version, kind="assessment_objective", source=test, target=first, actor=owner)
        services.link(version, kind="assessment_objective", source=test, target=second, actor=owner)
        services.soft_delete_block(first, actor=owner)
        services.soft_delete_block(second, actor=owner)
    assert report_of(world).status == "complete"
    assert len(findings(world, kind="link_to_deleted")) == 2


def test_a_dismissed_ai_finding_carries_into_the_next_version(ai_world, django_capture_on_commit_callbacks):  # noqa: F811
    w = ai_world
    key = w["blocks"][AMBIGUOUS].block_key
    with organization_context(w["org"]):
        quality.dismiss(ai_findings(w)[("bloom_disagreement", key)], reason="مقصود", actor=w["owner"], role=Role.AUTHOR)
        with django_capture_on_commit_callbacks(execute=True):
            lifecycle.transition(w["version"], S.SUBMITTED, actor=w["owner"])
            lifecycle.transition(w["version"], S.IN_STAGE, actor=w["owner"], stage=1)
            lifecycle.transition(w["version"], S.RETURNED, actor=w["owner"])
        draft = w["version"].program.versions.get(status=S.DRAFT)
        with django_capture_on_commit_callbacks(execute=True):
            services.update_node(draft.nodes.get(), title="عنوان", actor=w["owner"])
        carried = Finding.objects.get(report__version=draft, kind="bloom_disagreement", block_key=key)
        assert carried.dismissed_reason == "مقصود"
        quality.restore(carried, actor=w["owner"], role=Role.AUTHOR)
        with django_capture_on_commit_callbacks(execute=True):
            services.update_node(draft.nodes.get(), title="عنوان آخر", actor=w["owner"])
        again = Finding.objects.get(report__version=draft, kind="bloom_disagreement", block_key=key)
        assert again.dismissed_at is None, "carried once: a restore in the new version sticks"


def test_a_final_run_that_could_not_be_queued_is_failed_and_can_be_run_again(
    world,  # noqa: F811
    monkeypatch,
    django_capture_on_commit_callbacks,  # noqa: F811
):
    from apps.quality import tasks

    def down(*args, **kwargs):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks.run_report, "apply_async", down)
    monkeypatch.setattr(quality.sentry_sdk, "capture_exception", lambda exc: None)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    report = report_of(world)
    assert report.status == "failed" and "queue" in report.error
    monkeypatch.undo()
    run = login("author@example.com").post(
        f"/api/program-versions/{world['version'].pk}/quality/run/", {}, format="json"
    )
    assert run.status_code == 202


def test_a_run_left_running_by_a_lost_worker_can_be_run_again_after_a_while(
    world,  # noqa: F811
    settings,
    django_capture_on_commit_callbacks,  # noqa: F811
):
    from datetime import timedelta

    from django.utils import timezone

    with organization_context(world["org"]):
        with django_capture_on_commit_callbacks(execute=False):
            lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
            quality.request_run(world["version"], QualityReport.Run.FULL, final=True)
    client = login("author@example.com")
    url = f"/api/program-versions/{world['version'].pk}/quality/run/"
    assert client.post(url, {}, format="json").status_code == 409, "a run that is still going is left alone"
    QualityReport.all_organizations.filter(version=world["version"]).update(
        started_at=timezone.now() - timedelta(minutes=settings.QUALITY_STALE_RUN_MINUTES + 1)
    )
    assert client.post(url, {}, format="json").status_code == 202


def test_an_error_while_writing_the_results_fails_the_report_instead_of_leaving_it_running(
    world,  # noqa: F811
    monkeypatch,
    django_capture_on_commit_callbacks,  # noqa: F811
):
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(quality, "_write_rules", broken)
    monkeypatch.setattr(quality.sentry_sdk, "capture_exception", lambda exc: None)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        quality.request_run(world["version"], "full")
    report = report_of(world)
    assert report.status == "failed" and "disk full" in report.error


@pytest.mark.django_db(transaction=True)
def test_a_dismissal_and_a_run_take_their_locks_in_the_same_order(world):  # noqa: F811
    """dismiss locked the finding then the report; a run locks the report then deletes the findings: deadlock."""
    [vague] = findings(world, kind="objective_unmeasurable")
    report = report_of(world)
    errors = []
    holding = threading.Event()

    def run_holding_the_report():
        try:
            with organization_context(world["org"]), transaction.atomic():
                QualityReport.objects.select_for_update().get(pk=report.pk)
                holding.set()
                threading.Event().wait(0.5)
                Finding.objects.filter(pk=vague.pk).delete()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            close_old_connections()
            connection.close()

    thread = threading.Thread(target=run_holding_the_report)
    thread.start()
    assert holding.wait(5)
    with organization_context(world["org"]), pytest.raises(quality.QualityError) as raised:
        quality.dismiss(vague, reason="مقصود", actor=world["owner"], role=Role.AUTHOR)
    assert raised.value.get_codes() == "finding_outdated"
    thread.join()
    assert errors == []
    assert not findings(world, kind="objective_unmeasurable", dismissed_at__isnull=False)
