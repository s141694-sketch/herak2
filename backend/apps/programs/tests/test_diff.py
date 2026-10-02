"""Task 2.7, and the phase 2 completion criterion: a program on a four-level template, two versions, a correct diff."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.programs import diff, lifecycle, services
from apps.programs.models import AlignmentLink, ProgramVersion
from apps.tenancy.context import organization_context

from .factories import member, program

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status
K = AlignmentLink.Kind


def doc(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


@pytest.fixture
def two_versions():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        prog = program(owner)
        assert prog.template_version.levels.count() == 4
        v1 = prog.versions.get()
        competencies = list(v1.framework_version.competencies.all())

        root = services.add_node(v1, title="برنامج السلامة", actor=owner)
        m1 = services.add_node(v1, title="الوحدة الأولى", parent=root, actor=owner)
        m2 = services.add_node(v1, title="الوحدة الثانية", parent=root, actor=owner)
        lesson = services.add_node(v1, title="الدرس", parent=m1, actor=owner)
        activity = services.add_node(v1, title="النشاط", parent=lesson, actor=owner)
        keep = services.add_block(v1, node=lesson, type="objective", content=doc("يصف المتدرب الإجراء"), actor=owner)
        edit = services.add_block(v1, node=lesson, type="content", content=doc("نص قديم"), actor=owner)
        drop = services.add_block(v1, node=m2, type="reference", content=doc("مرجع"), actor=owner)
        move = services.add_block(v1, node=activity, type="activity", content=doc("ناقش"), actor=owner)
        assessment = services.add_block(v1, node=lesson, type="assessment", content=doc("سؤال"), actor=owner)
        services.link(v1, kind=K.OBJECTIVE_COMPETENCY, source=keep, competency=competencies[0], actor=owner)
        services.link(v1, kind=K.ASSESSMENT_OBJECTIVE, source=assessment, target=keep, actor=owner)

        lifecycle.transition(v1, S.SUBMITTED, actor=owner)
        lifecycle.transition(v1, S.WITHDRAWN, actor=owner)
        v2 = prog.versions.get(number=2)

        def in_v2(obj):
            model = type(obj)
            key = "node_key" if hasattr(obj, "node_key") else "block_key"
            return model.objects.get(version=v2, **{key: getattr(obj, key)})

        services.update_node(in_v2(m1), title="الوحدة الأولى (معدّلة)", actor=owner)
        services.move_node(in_v2(lesson), parent=in_v2(m2), order=1, actor=owner)
        services.update_block(in_v2(edit), content=doc("نص جديد"), actor=owner)
        services.soft_delete_block(in_v2(drop), actor=owner)
        services.update_block(in_v2(move), node=in_v2(m2), actor=owner)
        added_node = services.add_node(v2, title="الوحدة الثالثة", parent=in_v2(root), actor=owner)
        added_block = services.add_block(v2, node=added_node, type="objective", content=doc("هدف جديد"), actor=owner)
        services.unlink(v2.alignment_links.get(kind=K.ASSESSMENT_OBJECTIVE), actor=owner)
        services.link(v2, kind=K.OBJECTIVE_COMPETENCY, source=added_block, competency=competencies[1], actor=owner)
        services.set_targets(v2, [competencies[0].pk], actor=owner)

        refs = {
            "root": root,
            "m1": m1,
            "m2": m2,
            "lesson": lesson,
            "activity": activity,
            "added_node": added_node,
            "keep": keep,
            "edit": edit,
            "drop": drop,
            "move": move,
            "assessment": assessment,
            "added_block": added_block,
        }
        yield org, owner, v1, v2, refs


def by_key(entries, key_name):
    return {str(e[key_name]): e for e in entries}


def test_node_changes(two_versions):
    org, owner, v1, v2, r = two_versions
    with organization_context(org):
        result = diff.diff_versions(v1, v2)
    nodes = by_key(result["nodes"], "node_key")
    assert nodes[str(r["root"].node_key)]["change"] == "unchanged"
    assert nodes[str(r["m1"].node_key)]["change"] == "modified"
    assert nodes[str(r["m1"].node_key)]["fields"] == ["title"]
    assert nodes[str(r["lesson"].node_key)]["change"] == "moved"
    assert nodes[str(r["lesson"].node_key)]["fields"] == ["parent"]
    assert nodes[str(r["activity"].node_key)]["change"] == "unchanged", (
        "a child moved with its parent keeps its own place"
    )
    assert nodes[str(r["added_node"].node_key)]["change"] == "added"
    assert result["summary"]["nodes"] == {"added": 1, "removed": 0, "modified": 1, "moved": 1, "unchanged": 3}


def test_block_changes(two_versions):
    org, owner, v1, v2, r = two_versions
    with organization_context(org):
        result = diff.diff_versions(v1, v2)
    blocks = by_key(result["blocks"], "block_key")
    assert blocks[str(r["keep"].block_key)]["change"] == "unchanged"
    edited = blocks[str(r["edit"].block_key)]
    assert edited["change"] == "modified" and edited["fields"] == ["content"]
    assert (edited["text_before"], edited["text_after"]) == ("نص قديم", "نص جديد")
    assert blocks[str(r["drop"].block_key)]["change"] == "removed", "a soft-deleted block counts as removed"
    assert blocks[str(r["move"].block_key)]["change"] == "moved"
    assert blocks[str(r["added_block"].block_key)]["change"] == "added"
    assert result["summary"]["blocks"] == {"added": 1, "removed": 1, "modified": 1, "moved": 1, "unchanged": 2}


def test_link_and_target_changes(two_versions):
    org, owner, v1, v2, r = two_versions
    with organization_context(org):
        result = diff.diff_versions(v1, v2)
    assert [(link["kind"], link["source_key"]) for link in result["links"]["removed"]] == [
        ("assessment_objective", str(r["assessment"].block_key))
    ]
    assert [(link["kind"], link["source_key"]) for link in result["links"]["added"]] == [
        ("objective_competency", str(r["added_block"].block_key))
    ]
    assert [t["code"] for t in result["targets"]["removed"]] == ["C-2"]
    assert result["targets"]["added"] == []


def test_a_version_compared_with_itself_has_no_changes(two_versions):
    org, owner, v1, v2, r = two_versions
    with organization_context(org):
        result = diff.diff_versions(v1, v1)
    assert all(e["change"] == "unchanged" for e in result["nodes"] + result["blocks"])
    assert result["links"] == {"added": [], "removed": []}


def test_versions_of_different_programs_cannot_be_compared(two_versions):
    org, owner, v1, v2, r = two_versions
    with organization_context(org):
        other = program(owner, title="آخر").versions.get()
        with pytest.raises(services.ProgramError) as excinfo:
            diff.diff_versions(v1, other)
    assert excinfo.value.get_codes() == "diff_programs_differ"


def test_diff_endpoint(two_versions):
    org, owner, v1, v2, r = two_versions
    client = APIClient()
    client.post("/api/auth/login/", {"email": "owner@example.com", "password": "x" * 12}, format="json")
    response = client.get(f"/api/program-versions/{v1.pk}/diff/{v2.pk}/")
    assert response.status_code == 200
    body = response.json()
    assert (body["from"]["number"], body["to"]["number"]) == (1, 2)
    assert body["summary"]["blocks"]["modified"] == 1
