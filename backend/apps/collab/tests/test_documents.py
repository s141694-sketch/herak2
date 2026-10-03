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


def test_a_failed_materialization_keeps_the_last_good_rows_and_records_the_error(world):
    v = world["version"]
    assert (
        service()
        .put(url(v), {"state": "AQ==", "rows": rows_for(world, objective_text="أول حفظ")}, format="json")
        .status_code
        == 200
    )
    bad = rows_for(world, objective_text="ثاني")
    bad["blocks"][0]["content"] = {"type": "doc", "content": [{"type": "iframe"}]}
    response = service().put(url(v), {"state": "Ag==", "rows": bad}, format="json")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "materialization_failed"
    with organization_context(world["org"]):
        world["objective"].refresh_from_db()
        assert world["objective"].content == doc("أول حفظ")
        draft = DraftDocument.objects.get(version=v)
        assert bytes(draft.state) == b"\x01", "the state that failed is not stored over the last good one"
        assert "content" in draft.last_error and draft.last_error_at


def test_nodes_deeper_than_the_template_fail_materialization(world):
    rows = rows_for(world)
    rows["nodes"].append(
        {
            "node_key": "66666666-6666-4666-8666-666666666666",
            "parent_key": str(world["root"].node_key),
            "level": 4,
            "order": 1,
            "title": "عميق",
            "deleted": False,
        }
    )
    assert service().put(url(world["version"]), {"state": "AA==", "rows": rows}, format="json").status_code == 422


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


def test_a_new_draft_copies_the_yjs_state(world):
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
