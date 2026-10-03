"""Tasks 3.4 and 3.8: a live draft is frozen and its snapshot applied before it leaves draft status, then locked.

Django never waits on a call that comes back into Django: the collaboration service answers a freeze or a
snapshot with the document itself (review finding: a flush that saved through Django could exhaust the workers).
"""

import base64

import pytest
from django.conf import settings
from django.dispatch import receiver
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.collab import client as collab_client
from apps.collab.models import DraftDocument
from apps.collab.tests.test_documents import doc
from apps.programs import lifecycle, services
from apps.programs.models import Block, ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


class FakeCollab:
    """The collaboration service as Django sees it: a document per version, frozen by token."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.fail = False
        self.document: dict | None = None  # {"rows": ..., "state": bytes, "seq": int} while the document is open
        self.failure: dict | None = None  # what a freeze or snapshot answers when the document cannot be read
        self.seq = 1_000

    def __call__(self, action, document, *, query=None, timeout=None):
        self.calls.append((action, document, query) if query else (action, document))
        if self.fail:
            raise collab_client.CollabUnavailable("connection refused")
        if action == "lock":
            return {"status": "locked", "loaded": self.document is not None}
        if action == "unfreeze":
            return {"status": "unfrozen"}
        token = {"token": "t-1"} if action == "freeze" else {}
        if self.failure:
            return {**self.failure, **token}
        if self.document is None:
            return {"status": "not_loaded", **token}
        self.seq += 1
        return {
            "status": "snapshot",
            "seq": self.seq,
            "state": base64.b64encode(self.document["state"]).decode(),
            "rows": self.document["rows"],
            "actor_id": None,
            **token,
        }


@pytest.fixture
def world(monkeypatch):
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        version = program(owner).versions.get()
        root = services.add_node(version, title="البرنامج", actor=owner)
        objective = services.add_block(version, node=root, type="objective", content=doc("هدف"), actor=owner)
    fake = FakeCollab()
    monkeypatch.setattr(collab_client, "call", fake)
    return {"org": org, "owner": owner, "version": version, "root": root, "objective": objective, "fake": fake}


def name_of(version):
    return f"program-version:{version.pk}"


def make_live(w):
    with organization_context(w["org"]):
        DraftDocument.objects.create(version=w["version"], state=b"\x01")


def open_document(w, objective_text="هدف من المحرر", title="البرنامج"):
    w["fake"].document = {
        "state": b"\x02\x03",
        "rows": {
            "nodes": [
                {
                    "node_key": str(w["root"].node_key),
                    "parent_key": None,
                    "level": 0,
                    "order": 1,
                    "title": title,
                    "deleted": False,
                }
            ],
            "blocks": [
                {
                    "block_key": str(w["objective"].block_key),
                    "node_key": str(w["root"].node_key),
                    "type": "objective",
                    "order": 1,
                    "deleted": False,
                    "content": doc(objective_text),
                }
            ],
            "links": [],
        },
    }


def submit(w, *, run_on_commit=True, capture=None):
    with organization_context(w["org"]):
        if capture is None:
            return lifecycle.transition(w["version"], S.SUBMITTED, actor=w["owner"])
        with capture(execute=run_on_commit):
            return lifecycle.transition(w["version"], S.SUBMITTED, actor=w["owner"])


def test_an_open_draft_is_frozen_its_snapshot_applied_then_locked(world, django_capture_on_commit_callbacks):
    make_live(world)
    open_document(world, objective_text="آخر ما كُتب قبل الإرسال")
    submit(world, capture=django_capture_on_commit_callbacks)
    name = name_of(world["version"])
    assert world["fake"].calls == [("freeze", name), ("lock", name)]
    with organization_context(world["org"]):
        assert Block.objects.get(pk=world["objective"].pk).content == doc("آخر ما كُتب قبل الإرسال")
        draft = DraftDocument.objects.get(version=world["version"])
        assert bytes(draft.state) == b"\x02\x03" and draft.saved_seq == world["fake"].seq
        world["version"].refresh_from_db()
    assert world["version"].status == S.SUBMITTED


def test_a_draft_nobody_has_open_is_still_frozen_in_case_it_opens_meanwhile(world, django_capture_on_commit_callbacks):
    submit(world, capture=django_capture_on_commit_callbacks)
    name = name_of(world["version"])
    assert world["fake"].calls == [("freeze", name), ("lock", name)]


def test_an_unreachable_collab_does_not_block_a_draft_that_was_never_live(world):
    world["fake"].fail = True
    submit(world)
    world["version"].refresh_from_db()
    assert world["version"].status == S.SUBMITTED


def test_an_unreachable_collab_blocks_a_live_draft(world):
    make_live(world)
    world["fake"].fail = True
    with pytest.raises(lifecycle.TransitionRefused) as excinfo:
        submit(world)
    assert excinfo.value.get_codes() == "collab_unavailable"


def test_a_snapshot_that_cannot_be_applied_blocks_submission_keeps_its_state_and_unfreezes(world):
    make_live(world)
    open_document(world, title="ط" * 501)
    with pytest.raises(lifecycle.TransitionRefused) as excinfo:
        submit(world)
    assert excinfo.value.get_codes() == "materialization_failed"
    name = name_of(world["version"])
    assert world["fake"].calls == [("freeze", name), ("unfreeze", name, {"token": "t-1"})]
    with organization_context(world["org"]):
        world["version"].refresh_from_db()
        assert world["version"].status == S.DRAFT
        draft = DraftDocument.objects.get(version=world["version"])
        assert bytes(draft.state) == b"\x02\x03", "the live state is kept, so nothing typed is lost"
        assert draft.last_error_code == "node_title_invalid"


def test_a_document_the_service_cannot_read_blocks_submission_and_unfreezes(world):
    make_live(world)
    world["fake"].failure = {"status": "failed", "error": "materialize: bad block", "code": "document_invalid"}
    with pytest.raises(lifecycle.TransitionRefused) as excinfo:
        submit(world)
    assert excinfo.value.get_codes() == "materialization_failed"
    assert world["fake"].calls[-1] == ("unfreeze", name_of(world["version"]), {"token": "t-1"})


def test_a_refusal_after_the_freeze_unfreezes_the_document(world):
    make_live(world)
    open_document(world)

    @receiver(lifecycle.leaving_draft, weak=False)
    def refuse(sender, **kwargs):
        raise lifecycle.TransitionRefused("not today", code="not_today")

    try:
        with pytest.raises(lifecycle.TransitionRefused):
            submit(world)
    finally:
        lifecycle.leaving_draft.disconnect(refuse)
    assert world["fake"].calls[-1] == ("unfreeze", name_of(world["version"]), {"token": "t-1"})


def test_an_error_after_the_status_changed_still_unfreezes_the_document(world):
    """The transaction rolls back, so the draft stays a draft and its editors get the document back."""
    make_live(world)
    open_document(world)

    @receiver(lifecycle.left_draft, weak=False)
    def fail(sender, **kwargs):
        raise RuntimeError("disk full")

    try:
        with pytest.raises(RuntimeError):
            submit(world)
    finally:
        lifecycle.left_draft.disconnect(fail)
    assert world["fake"].calls[-1] == ("unfreeze", name_of(world["version"]), {"token": "t-1"})
    world["version"].refresh_from_db()
    assert world["version"].status == S.DRAFT


def test_a_recorded_materialization_error_blocks_submission_when_nobody_has_the_document_open(world):
    make_live(world)
    with organization_context(world["org"]):
        DraftDocument.objects.filter(version=world["version"]).update(last_error="block y: content invalid")
    with pytest.raises(lifecycle.TransitionRefused) as excinfo:
        submit(world)
    assert excinfo.value.get_codes() == "materialization_failed"


def test_a_snapshot_that_applies_clears_an_earlier_error(world, django_capture_on_commit_callbacks):
    make_live(world)
    with organization_context(world["org"]):
        DraftDocument.objects.filter(version=world["version"]).update(last_error="block y: content invalid")
    open_document(world)
    submit(world, capture=django_capture_on_commit_callbacks)
    world["version"].refresh_from_db()
    assert world["version"].status == S.SUBMITTED


def test_the_api_reports_the_reason_and_the_draft_status(world):
    make_live(world)
    with organization_context(world["org"]):
        DraftDocument.objects.filter(version=world["version"]).update(
            last_error="block y: content invalid", last_error_code="block_content_invalid"
        )
    client = APIClient()
    client.post("/api/auth/login/", {"email": "owner@example.com", "password": "x" * 12}, format="json")
    response = client.post(f"/api/program-versions/{world['version'].pk}/submit/")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "materialization_failed"
    live = client.get(f"/api/program-versions/{world['version'].pk}/").json()["live"]
    assert live["is_live"] is True and live["last_error"] == "block y: content invalid"
    assert live["last_error_code"] == "block_content_invalid", "the page translates the code, not the message"


def test_the_comparison_reads_a_snapshot_of_an_open_draft_without_freezing_it(world):
    make_live(world)
    open_document(world, objective_text="نص لم يُحفظ بعد")
    client = APIClient()
    client.post("/api/auth/login/", {"email": "owner@example.com", "password": "x" * 12}, format="json")
    version = world["version"]
    assert client.get(f"/api/program-versions/{version.pk}/diff/{version.pk}/").status_code == 200
    assert world["fake"].calls == [("snapshot", name_of(version))]
    with organization_context(world["org"]):
        assert Block.objects.get(pk=world["objective"].pk).content == doc("نص لم يُحفظ بعد")


def test_the_comparison_still_answers_when_the_snapshot_cannot_be_applied(world):
    make_live(world)
    open_document(world, title="ط" * 501)
    client = APIClient()
    client.post("/api/auth/login/", {"email": "owner@example.com", "password": "x" * 12}, format="json")
    version = world["version"]
    assert client.get(f"/api/program-versions/{version.pk}/diff/{version.pk}/").status_code == 200


def test_the_client_signs_its_calls_and_passes_the_token_and_timeout(monkeypatch):
    import importlib

    importlib.reload(collab_client)  # undo the autouse stub: this test exercises the real client
    seen = {}

    class Response:
        status = 200

        def read(self):
            return b'{"status": "unfrozen"}'

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
    assert collab_client.call("unfreeze", "program-version:5", query={"token": "a b"}, timeout=2) == {
        "status": "unfrozen"
    }
    assert seen["url"] == f"{settings.COLLAB_INTERNAL_URL}/internal/documents/program-version%3A5/unfreeze?token=a+b"
    assert seen["auth"] == f"Service {settings.COLLAB_SERVICE_SECRET}"
    assert seen["timeout"] == 2
    collab_client.call("lock", "program-version:5")
    assert seen["timeout"] == settings.COLLAB_TIMEOUT_SECONDS
