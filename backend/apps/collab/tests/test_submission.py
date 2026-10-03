"""Tasks 3.4 and 3.8: the live document is flushed before a draft leaves draft status, and locked after."""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.collab import client as collab_client
from apps.collab.models import DraftDocument
from apps.programs import lifecycle
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


class FakeCollab:
    def __init__(self, flush_result=None, fail=False):
        self.calls: list[tuple[str, str]] = []
        self.flush_result = flush_result or {"status": "saved", "error": None}
        self.fail = fail

    def __call__(self, action, document):
        self.calls.append((action, document))
        if self.fail:
            raise collab_client.CollabUnavailable("connection refused")
        return self.flush_result if action == "flush" else {"status": "locked"}


@pytest.fixture
def world(monkeypatch, django_capture_on_commit_callbacks):
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        version = program(owner).versions.get()
    fake = FakeCollab()
    monkeypatch.setattr(collab_client, "call", fake)
    return org, owner, version, fake


def make_live(org, version):
    with organization_context(org):
        DraftDocument.objects.create(version=version, state=b"\x01")


def test_a_draft_never_saved_live_is_still_flushed_in_case_it_is_open(world, django_capture_on_commit_callbacks):
    org, owner, version, fake = world
    fake.flush_result = {"status": "not_loaded"}
    with organization_context(org), django_capture_on_commit_callbacks(execute=True):
        lifecycle.transition(version, S.SUBMITTED, actor=owner)
    name = f"program-version:{version.pk}"
    assert fake.calls == [("flush", name), ("lock", name)]


def test_an_unreachable_collab_does_not_block_a_draft_that_was_never_live(world):
    org, owner, version, fake = world
    fake.fail = True
    with organization_context(org):
        lifecycle.transition(version, S.SUBMITTED, actor=owner)
        version.refresh_from_db()
    assert version.status == S.SUBMITTED


def test_the_comparison_flushes_a_live_draft_first(world):
    org, owner, version, fake = world
    client = APIClient()
    client.post("/api/auth/login/", {"email": "owner@example.com", "password": "x" * 12}, format="json")
    assert client.get(f"/api/program-versions/{version.pk}/diff/{version.pk}/").status_code == 200
    assert fake.calls == [("flush", f"program-version:{version.pk}")]


def test_a_live_draft_is_flushed_before_submission_and_locked_after(world, django_capture_on_commit_callbacks):
    org, owner, version, fake = world
    make_live(org, version)
    with organization_context(org), django_capture_on_commit_callbacks(execute=True):
        lifecycle.transition(version, S.SUBMITTED, actor=owner)
    name = f"program-version:{version.pk}"
    assert fake.calls == [("flush", name), ("lock", name)]


@pytest.mark.parametrize("flush_result", [{"status": "failed", "error": "block x: content invalid"}])
def test_a_failed_flush_blocks_submission(world, flush_result):
    org, owner, version, fake = world
    make_live(org, version)
    fake.flush_result = flush_result
    with organization_context(org):
        with pytest.raises(lifecycle.TransitionRefused) as excinfo:
            lifecycle.transition(version, S.SUBMITTED, actor=owner)
        assert excinfo.value.get_codes() == "materialization_failed"
        version.refresh_from_db()
        assert version.status == S.DRAFT


def test_an_unreachable_collab_blocks_submission(world):
    org, owner, version, fake = world
    make_live(org, version)
    fake.fail = True
    with organization_context(org), pytest.raises(lifecycle.TransitionRefused) as excinfo:
        lifecycle.transition(version, S.SUBMITTED, actor=owner)
    assert excinfo.value.get_codes() == "collab_unavailable"


def test_a_recorded_materialization_error_blocks_submission_even_when_flush_succeeds(world):
    org, owner, version, fake = world
    make_live(org, version)
    with organization_context(org):
        DraftDocument.objects.filter(version=version).update(last_error="block y: content invalid")
        with pytest.raises(lifecycle.TransitionRefused) as excinfo:
            lifecycle.transition(version, S.SUBMITTED, actor=owner)
    assert excinfo.value.get_codes() == "materialization_failed"


def test_the_api_reports_the_reason_and_the_draft_status(world):
    org, owner, version, fake = world
    make_live(org, version)
    with organization_context(org):
        DraftDocument.objects.filter(version=version).update(last_error="block y: content invalid")
    client = APIClient()
    client.post("/api/auth/login/", {"email": "owner@example.com", "password": "x" * 12}, format="json")
    response = client.post(f"/api/program-versions/{version.pk}/submit/")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "materialization_failed"
    live = client.get(f"/api/program-versions/{version.pk}/").json()["live"]
    assert live["is_live"] is True and live["last_error"] == "block y: content invalid"


def test_the_client_signs_its_calls_with_the_service_secret(monkeypatch):
    import importlib

    importlib.reload(collab_client)  # undo the autouse stub: this test exercises the real client
    seen = {}

    class Response:
        status = 200

        def read(self):
            return b'{"status": "saved"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.headers["Authorization"]
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(collab_client.urllib.request, "urlopen", fake_urlopen)
    assert collab_client.call("flush", "program-version:5") == {"status": "saved"}
    assert seen["url"] == f"{settings.COLLAB_INTERNAL_URL}/internal/documents/program-version%3A5/flush"
    assert seen["auth"] == f"Service {settings.COLLAB_SERVICE_SECRET}"
