"""The export on approval (task 7.5; spec 6.4, 7.7; D79): the final approval asks for it, it runs in the
background with retries at growing intervals, and makes the Word file and its PDF; a failure never undoes the
approval, says what happened, and can be tried again."""

import pytest
from rest_framework.test import APIClient

from apps.exports import jobs, pdf
from apps.exports.models import ExportJob
from apps.files import storage
from apps.notifications.models import Notification
from apps.notifications.tests.test_automation import act, decide, submit, world  # noqa: F401
from apps.programs.models import ProgramVersion
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status
FAKE_PDF = b"%PDF-1.7 made in the test"


@pytest.fixture
def converter(monkeypatch):
    """LibreOffice stands aside (its own test is in test_pdf.py): each call answers from the script, in turn."""
    calls = []

    def convert(docx):
        calls.append(docx)
        outcome = script.pop(0) if script else FAKE_PDF
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    script: list = []
    monkeypatch.setattr(pdf, "from_word", convert)
    return {"calls": calls, "script": script}


def approve(world, act):  # noqa: F811
    submit(world, act)
    decide(world, act, world["reviewer"], "approve")
    decide(world, act, world["approver"], "approve")


def job_of(world):  # noqa: F811
    with organization_context(world["org"]):
        return ExportJob.objects.select_related("word_file", "pdf_file", "version").get(version=world["version"])


def test_the_final_approval_makes_the_word_file_and_the_pdf_and_marks_the_version_exported(world, act, converter):  # noqa: F811
    approve(world, act)
    job = job_of(world)
    assert (job.status, job.attempts) == (ExportJob.Status.DONE, 1)
    assert job.word_file.name.endswith(".docx") and job.pdf_file.name.endswith(".pdf")
    assert storage.read(job.word_file.key).startswith(b"PK") and storage.read(job.pdf_file.key) == FAKE_PDF
    assert job.version.status == S.EXPORTED
    assert len(converter["calls"]) == 1


def test_a_failed_attempt_is_tried_again_and_the_approval_stands_meanwhile(world, act, converter):  # noqa: F811
    converter["script"].extend([pdf.ConversionFailed("LibreOffice took too long"), FAKE_PDF])
    approve(world, act)
    job = job_of(world)
    assert (job.status, job.attempts) == (ExportJob.Status.DONE, 2)
    assert job.version.status == S.EXPORTED


def test_an_export_that_keeps_failing_says_so_tells_the_admins_and_keeps_the_approval(world, act, converter):  # noqa: F811
    converter["script"].extend([pdf.ConversionFailed("no PDF")] * jobs.MAX_ATTEMPTS)
    approve(world, act)
    job = job_of(world)
    assert (job.status, job.attempts) == (ExportJob.Status.FAILED, jobs.MAX_ATTEMPTS)
    assert "no PDF" in job.last_error
    assert job.version.status == S.APPROVED  # never undone
    with organization_context(world["org"]):
        told = list(Notification.objects.filter(event="export_failed").values_list("recipient__email", flat=True))
    assert told == ["admin@example.com"]


def test_an_admin_tries_a_failed_export_again(world, act, converter):  # noqa: F811
    converter["script"].extend([pdf.ConversionFailed("no PDF")] * jobs.MAX_ATTEMPTS)
    approve(world, act)
    version = world["version"]
    author = APIClient()
    author.force_login(world["author"])
    assert author.post(f"/api/program-versions/{version.pk}/export/retry/").status_code == 403
    admin = APIClient()
    admin.force_login(world["admin"])
    response = act(lambda: admin.post(f"/api/program-versions/{version.pk}/export/retry/"))
    assert response.status_code == 200, response.content
    assert job_of(world).status == ExportJob.Status.DONE


def test_handling_the_approval_again_makes_no_second_export(world, act, converter):  # noqa: F811
    approve(world, act)
    with organization_context(world["org"]):
        jobs.request_export(world["version"])
        jobs.run(job_of(world).pk)
    assert ExportJob.all_organizations.count() == 1 and len(converter["calls"]) == 1


def test_the_sweep_picks_up_an_approval_whose_export_never_started(world, act, converter, monkeypatch):  # noqa: F811
    monkeypatch.setattr(jobs, "enqueue", lambda job: None)  # the broker was down when it was approved
    approve(world, act)
    assert job_of(world).status == ExportJob.Status.PENDING
    monkeypatch.undo()
    monkeypatch.setattr(pdf, "from_word", lambda docx: FAKE_PDF)
    ExportJob.all_organizations.update(updated_at="2026-01-01T00:00Z")  # waiting long enough to be taken up
    jobs.sweep()
    assert job_of(world).status == ExportJob.Status.DONE


def test_members_see_the_export_and_download_its_files(world, act, converter):  # noqa: F811
    approve(world, act)
    reader = APIClient()
    reader.force_login(world["reviewer"])
    body = reader.get(f"/api/program-versions/{world['version'].pk}/export/").json()
    assert body["status"] == "done" and body["word"]["name"].endswith(".docx") and body["pdf"]["name"].endswith(".pdf")
    assert reader.get(f"/api/files/{body['pdf']['id']}/download/").status_code == 302


def test_a_version_not_approved_has_no_export(world):  # noqa: F811
    reader = APIClient()
    reader.force_login(world["author"])
    assert reader.get(f"/api/program-versions/{world['version'].pk}/export/").json() == {"status": "none"}
