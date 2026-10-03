import base64

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.collab.models import DraftDocument
from apps.programs import lifecycle, services
from apps.programs.models import AlignmentLink, Block, Node, ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


def doc(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def service(secret=None):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Service {secret or settings.COLLAB_SERVICE_SECRET}")
    return client


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        version = program(owner).versions.get()
        root = services.add_node(version, title="البرنامج", actor=owner)
        objective = services.add_block(version, node=root, type="objective", content=doc("هدف"), actor=owner)
        assessment = services.add_block(version, node=root, type="assessment", content=doc("سؤال"), actor=owner)
        competency = version.framework_version.competencies.first()
        services.link(version, kind="objective_competency", source=objective, competency=competency, actor=owner)
        services.link(version, kind="assessment_objective", source=assessment, target=objective, actor=owner)
    return {
        "org": org,
        "owner": owner,
        "version": version,
        "root": root,
        "objective": objective,
        "assessment": assessment,
        "competency": competency,
    }


def url(version):
    return f"/api/internal/collab/documents/{version.pk}/"


def rows_for(w, *, objective_text="هدف معدّل", extra_node=None, extra_block=None, drop_link=False):
    root, objective, assessment = w["root"], w["objective"], w["assessment"]
    nodes = [
        {
            "node_key": str(root.node_key),
            "parent_key": None,
            "level": 0,
            "order": 1,
            "title": "البرنامج المعدّل",
            "deleted": False,
        }
    ]
    if extra_node:
        nodes.append(extra_node)
    blocks = [
        {
            "block_key": str(objective.block_key),
            "node_key": str(root.node_key),
            "type": "objective",
            "order": 1,
            "deleted": False,
            "content": doc(objective_text),
        },
        {
            "block_key": str(assessment.block_key),
            "node_key": str(root.node_key),
            "type": "assessment",
            "order": 2,
            "deleted": False,
            "content": doc("سؤال"),
        },
    ]
    if extra_block:
        blocks.append(extra_block)
    links = [
        {
            "link_key": "11111111-1111-4111-8111-111111111111",
            "kind": "objective_competency",
            "source_key": str(objective.block_key),
            "target_key": None,
            "competency_key": str(w["competency"].competency_key),
        },
    ]
    if not drop_link:
        links.append(
            {
                "link_key": "22222222-2222-4222-8222-222222222222",
                "kind": "assessment_objective",
                "source_key": str(assessment.block_key),
                "target_key": str(objective.block_key),
                "competency_key": None,
            }
        )
    return {"nodes": nodes, "blocks": blocks, "links": links, "issues": []}


def test_service_endpoints_require_the_service_secret(world):
    assert APIClient().get(url(world["version"])).status_code == 403
    assert service("wrong-secret-of-the-right-length-0123456").get(url(world["version"])).status_code == 403
    assert service().get("/api/internal/collab/documents/999999/").status_code == 404


def test_loading_a_version_without_state_returns_its_rows_in_document_form(world):
    body = service().get(url(world["version"])).json()
    assert body["editable"] is True and body["state"] is None and body["level_count"] == 4
    rows = body["rows"]
    assert [n["title"] for n in rows["nodes"]] == ["البرنامج"]
    assert {b["type"] for b in rows["blocks"]} == {"objective", "assessment"}
    kinds = {link["kind"]: link for link in rows["links"]}
    assert kinds["objective_competency"]["competency_key"] == str(world["competency"].competency_key)
    assert kinds["assessment_objective"]["target_key"] == str(world["objective"].block_key)


def test_saving_stores_the_state_and_upserts_rows_by_key(world):
    v = world["version"]
    new_node = {
        "node_key": "33333333-3333-4333-8333-333333333333",
        "parent_key": str(world["root"].node_key),
        "level": 1,
        "order": 1,
        "title": "وحدة جديدة",
        "deleted": False,
    }
    new_block = {
        "block_key": "44444444-4444-4444-8444-444444444444",
        "node_key": new_node["node_key"],
        "type": "content",
        "order": 1,
        "deleted": False,
        "content": doc("محتوى جديد"),
    }
    state = base64.b64encode(b"\x01\x02yjs-state").decode()
    response = service().put(
        url(v), {"state": state, "rows": rows_for(world, extra_node=new_node, extra_block=new_block)}, format="json"
    )
    assert response.status_code == 200, response.content
    with organization_context(world["org"]):
        draft = DraftDocument.objects.get(version=v)
        assert bytes(draft.state) == b"\x01\x02yjs-state" and draft.materialized_at and draft.last_error == ""
        world["objective"].refresh_from_db()
        assert world["objective"].content == doc("هدف معدّل"), "same row, updated in place"
        assert Node.objects.get(version=v, node_key=new_node["node_key"]).parent == world["root"]
        assert Block.objects.get(version=v, block_key=new_block["block_key"]).node.title == "وحدة جديدة"
        assert AlignmentLink.objects.filter(version=v).count() == 2
        assert AuditLog.objects.filter(event="program_version.materialized").exists()
    assert service().get(url(v)).json()["state"] == state


def test_rows_missing_from_the_document_are_soft_deleted_and_links_follow_the_document(world):
    v = world["version"]
    rows = rows_for(world, drop_link=True)
    rows["blocks"] = [b for b in rows["blocks"] if b["type"] == "objective"]
    assert service().put(url(v), {"state": "AA==", "rows": rows}, format="json").status_code == 200
    with organization_context(world["org"]):
        world["assessment"].refresh_from_db()
        assert world["assessment"].deleted is True
        assert list(AlignmentLink.objects.filter(version=v).values_list("kind", flat=True)) == ["objective_competency"]


def test_invalid_links_are_skipped_and_reported_not_fatal(world):
    v = world["version"]
    rows = rows_for(world)
    rows["links"].append(
        {
            "link_key": "55555555-5555-4555-8555-555555555555",
            "kind": "assessment_objective",
            "source_key": str(world["objective"].block_key),
            "target_key": str(world["assessment"].block_key),
            "competency_key": None,
        }
    )
    body = service().put(url(v), {"state": "AA==", "rows": rows}, format="json").json()
    assert body["skipped_links"] == ["55555555-5555-4555-8555-555555555555"]
    with organization_context(world["org"]):
        assert AlignmentLink.objects.filter(version=v).count() == 2


def test_a_failed_materialization_keeps_the_last_good_rows_and_the_newer_state(world, monkeypatch):
    """The rows stay at the last good save; the state is kept so a restart of the editor loses nothing typed."""
    alerts = []
    monkeypatch.setattr(
        "apps.collab.saving.sentry_sdk.capture_message", lambda message, level: alerts.append((message, level))
    )
    v = world["version"]
    first = {"state": "AQ==", "rows": rows_for(world, objective_text="أول حفظ"), "seq": 10}
    assert service().put(url(v), first, format="json").status_code == 200
    bad = rows_for(world, objective_text="ثاني")
    bad["blocks"][0]["content"] = {"type": "doc", "content": [{"type": "iframe"}]}
    response = service().put(url(v), {"state": "Ag==", "rows": bad, "seq": 11}, format="json")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "block_content_invalid" and error["details"] == {"state_saved": True}
    with organization_context(world["org"]):
        world["objective"].refresh_from_db()
        assert world["objective"].content == doc("أول حفظ")
        draft = DraftDocument.objects.get(version=v)
        assert bytes(draft.state) == b"\x02" and draft.saved_seq == 11
        assert "content" in draft.last_error and draft.last_error_at
        assert draft.last_error_code == "block_content_invalid"
    assert alerts and alerts[0][1] == "error", "a technical alert is raised"
    fixed = {"state": "Aw==", "rows": rows_for(world, objective_text="ثالث"), "seq": 12}
    assert service().put(url(v), fixed, format="json").status_code == 200
    with organization_context(world["org"]):
        draft = DraftDocument.objects.get(version=v)
        assert draft.last_error == "" and draft.last_error_code == "" and draft.last_error_at is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda rows: rows["nodes"][0].update(title="ط" * 501), "node_title_invalid"),
        (lambda rows: rows["blocks"][0].update(type="poem"), "rows_invalid"),
        (lambda rows: rows["nodes"][0].update(node_key="not-a-key"), "rows_invalid"),
    ],
)
def test_each_materialization_error_carries_a_code_the_editor_translates(world, change, code):
    rows = rows_for(world)
    change(rows)
    response = service().put(url(world["version"]), {"state": "AA==", "rows": rows, "seq": 1}, format="json")
    assert response.status_code == 422 and response.json()["error"]["code"] == code


def test_a_save_older_than_the_stored_one_changes_nothing(world):
    """A slow save may arrive after a newer one (a submission snapshot, a retry); the newer content stays."""
    v = world["version"]
    newer = {"state": "Ag==", "rows": rows_for(world, objective_text="أحدث"), "seq": 20}
    older = {"state": "AQ==", "rows": rows_for(world, objective_text="أقدم"), "seq": 19}
    assert service().put(url(v), newer, format="json").status_code == 200
    response = service().put(url(v), older, format="json")
    assert response.status_code == 200 and response.json()["stale"] is True
    with organization_context(world["org"]):
        world["objective"].refresh_from_db()
        assert world["objective"].content == doc("أحدث")
        assert bytes(DraftDocument.objects.get(version=v).state) == b"\x02"


def test_the_service_reports_a_document_it_cannot_read(world, monkeypatch):
    monkeypatch.setattr("apps.collab.saving.sentry_sdk.capture_message", lambda message, level: None)
    v = world["version"]
    response = service().post(
        f"{url(v)}failure/", {"error": "materialize: bad block", "code": "document_invalid"}, format="json"
    )
    assert response.status_code == 200
    with organization_context(world["org"]):
        draft = DraftDocument.objects.get(version=v)
        assert draft.last_error == "materialize: bad block" and draft.last_error_code == "document_invalid"
    unknown = service().post(f"{url(v)}failure/", {"error": "x", "code": "<script>"}, format="json")
    assert unknown.status_code == 200
    with organization_context(world["org"]):
        assert DraftDocument.objects.get(version=v).last_error_code == "document_invalid"


def test_nodes_deeper_than_the_template_fail_materialization(world):
    rows = rows_for(world)
    parent = str(world["root"].node_key)
    for level in range(1, 5):  # the template has four levels, 0 to 3
        key = f"6666666{level}-6666-4666-8666-666666666666"
        rows["nodes"].append(
            {"node_key": key, "parent_key": parent, "level": level, "order": 1, "title": "عميق", "deleted": False}
        )
        parent = key
    response = service().put(url(world["version"]), {"state": "AA==", "rows": rows}, format="json")
    assert response.status_code == 422 and response.json()["error"]["code"] == "node_too_deep"


def test_locked_versions_cannot_be_saved(world):
    with organization_context(world["org"]):
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    response = service().put(url(world["version"]), {"state": "AA==", "rows": rows_for(world)}, format="json")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_locked"
    assert service().get(url(world["version"])).json()["editable"] is False


def test_once_live_the_draft_refuses_rest_content_writes(world):
    service().put(url(world["version"]), {"state": "AA==", "rows": rows_for(world)}, format="json")
    with organization_context(world["org"]):
        with pytest.raises(services.ProgramError) as excinfo:
            services.add_node(world["version"], title="من REST", actor=world["owner"])
        assert excinfo.value.get_codes() == "draft_is_live"


def test_a_new_draft_copies_the_yjs_state(world, monkeypatch):
    from apps.collab import client as collab_client

    monkeypatch.setattr(collab_client, "call", lambda action, document, **kwargs: {"status": "not_loaded"})
    v1 = world["version"]
    service().put(url(v1), {"state": base64.b64encode(b"state-v1").decode(), "rows": rows_for(world)}, format="json")
    with organization_context(world["org"]):
        lifecycle.transition(v1, S.SUBMITTED, actor=world["owner"])
        lifecycle.transition(v1, S.WITHDRAWN, actor=world["owner"])
        v2 = v1.program.versions.get(number=2)
        assert bytes(DraftDocument.objects.get(version=v2).state) == b"state-v1"
        assert set(AlignmentLink.objects.filter(version=v2).values_list("link_key", flat=True)) == set(
            AlignmentLink.objects.filter(version=v1).values_list("link_key", flat=True)
        )


def test_a_draft_is_live_from_the_moment_the_editor_loads_it(world):
    """Before the first save, REST edits would be overwritten by the editor's next save without a word."""
    assert service().get(url(world["version"])).json()["state"] is None
    with organization_context(world["org"]):
        assert DraftDocument.objects.filter(version=world["version"]).exists()
        with pytest.raises(services.ProgramError) as excinfo:
            services.update_block(world["objective"], content=doc("من REST"), actor=world["owner"])
        assert excinfo.value.get_codes() == "draft_is_live"


def test_loading_a_locked_version_makes_no_live_draft(world):
    with organization_context(world["org"]):
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    service().get(url(world["version"]))
    with organization_context(world["org"]):
        assert not DraftDocument.objects.filter(version=world["version"]).exists()


def test_unchanged_links_keep_their_row_author_and_time_across_saves(world):
    """Review finding: every save recreated every link, rewriting who made it and when."""
    first = service().put(url(world["version"]), {"state": "AA==", "rows": rows_for(world)}, format="json")
    assert first.status_code == 200
    with organization_context(world["org"]):
        before = {
            str(link.link_key): (link.pk, link.created_by_id, link.created_at) for link in AlignmentLink.objects.all()
        }
        other = member("editor@example.com", Role.AUTHOR)
    second = service().put(
        url(world["version"]),
        {"state": "AA==", "rows": rows_for(world, objective_text="نص آخر"), "actor_id": other.pk},
        format="json",
    )
    assert second.status_code == 200
    with organization_context(world["org"]):
        after = {
            str(link.link_key): (link.pk, link.created_by_id, link.created_at) for link in AlignmentLink.objects.all()
        }
    assert after == before and len(after) == 2


def test_a_dropped_link_is_removed_and_a_new_one_created_under_its_key(world):
    service().put(url(world["version"]), {"state": "AA==", "rows": rows_for(world)}, format="json")
    service().put(url(world["version"]), {"state": "AA==", "rows": rows_for(world, drop_link=True)}, format="json")
    with organization_context(world["org"]):
        assert [str(k) for k in AlignmentLink.objects.values_list("link_key", flat=True)] == [
            "11111111-1111-4111-8111-111111111111"
        ]


def test_a_save_above_five_megabytes_is_accepted_up_to_its_own_limit(world, settings):
    big = base64.b64encode(b"x" * (6 * 1024 * 1024)).decode()
    response = service().put(url(world["version"]), {"state": big, "rows": rows_for(world)}, format="json")
    assert response.status_code == 200, response.content[:200]
    settings.COLLAB_SAVE_MAX_BYTES = 1024 * 1024
    refused = service().put(url(world["version"]), {"state": big, "rows": rows_for(world)}, format="json")
    assert refused.status_code == 413 and refused.json()["error"]["code"] == "document_too_large"


def test_internal_calls_are_not_redirected_to_https(world, settings):
    """In production SECURE_SSL_REDIRECT is on, but the collaboration service calls Django over plain HTTP."""
    settings.SECURE_SSL_REDIRECT = True
    assert service().get(url(world["version"])).status_code == 200
    assert APIClient().get("/api/health/").status_code == 301
