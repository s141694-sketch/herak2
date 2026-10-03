import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.audit.models import AuditLog
from apps.collab.models import DraftDocument
from apps.comments.models import Comment
from apps.programs import lifecycle, services
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status
ANCHOR = {"start": "AQIDBA==", "end": "BQYHCA=="}


def login(email):
    client = APIClient()
    client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json")
    return client


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("author@example.com", Role.AUTHOR)
        member("reviewer@example.com", Role.REVIEWER)
        member("pending@example.com", Role.PENDING)
        prog = program(owner)
        version = prog.versions.get()
        root = services.add_node(version, title="الوحدة", actor=owner)
        block = services.add_block(version, node=root, type="objective", actor=owner)
    return {"org": org, "owner": owner, "program": prog, "version": version, "root": root, "block": block}


def create(client, w, **extra):
    body = {
        "version": w["version"].pk,
        "block_key": str(w["block"].block_key),
        "anchor": ANCHOR,
        "quoted": "خطوات الإجراء",
        "body": "صِغ الهدف بفعل قابل للقياس",
        "category": "must_fix",
        **extra,
    }
    return client.post(f"/api/programs/{w['program'].pk}/comments/", body, format="json")


def test_a_reviewer_comments_on_a_quoted_range_and_everyone_sees_it(world):
    response = create(login("reviewer@example.com"), world)
    assert response.status_code == 201, response.content
    comment = response.json()
    assert comment["status"] == "open" and comment["category"] == "must_fix"
    assert comment["anchor"] == ANCHOR and comment["quoted"] == "خطوات الإجراء"
    assert comment["author"]["email"] == "reviewer@example.com"
    listed = login("author@example.com").get(f"/api/programs/{world['program'].pk}/comments/").json()
    assert [c["id"] for c in listed] == [comment["id"]]
    with organization_context(world["org"]):
        assert AuditLog.objects.filter(event="comment.created").exists()


def test_comments_on_a_node_need_no_anchor(world):
    response = create(
        login("reviewer@example.com"),
        world,
        block_key=None,
        node_key=str(world["root"].node_key),
        anchor=None,
        quoted="",
    )
    assert response.status_code == 201
    assert response.json()["node_key"] == str(world["root"].node_key)


@pytest.mark.parametrize(
    "extra,code",
    [
        ({"block_key": None}, "comment_target_missing"),
        ({"category": "nice_to_have"}, "validation_error"),
        ({"body": ""}, "validation_error"),
        ({"anchor": {"start": "not base64!", "end": "AA=="}}, "validation_error"),
    ],
)
def test_invalid_comments_are_refused(world, extra, code):
    response = create(login("reviewer@example.com"), world, **extra)
    assert response.status_code in (400, 409)
    assert response.json()["error"]["code"] == code


def test_a_draft_accepts_comments_on_blocks_not_yet_saved_as_rows(world):
    response = create(login("author@example.com"), world, block_key="11111111-1111-4111-8111-111111111111")
    assert response.status_code == 201


def test_a_locked_version_only_accepts_comments_on_its_rows(world):
    with organization_context(world["org"]):
        DraftDocument.objects.create(version=world["version"], state=b"\x01")
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    reviewer = login("reviewer@example.com")
    unknown = create(reviewer, world, block_key="00000000-0000-4000-8000-000000000000")
    assert unknown.status_code == 409 and unknown.json()["error"]["code"] == "comment_target_unknown"
    assert create(reviewer, world).status_code == 201


def test_pending_members_cannot_comment(world):
    assert create(login("pending@example.com"), world).status_code == 403


def test_replies_resolution_and_reopening(world):
    comment = create(login("reviewer@example.com"), world).json()
    author = login("author@example.com")
    reviewer = login("reviewer@example.com")
    assert (
        author.post(f"/api/comments/{comment['id']}/replies/", {"body": "عُدّل، شكرًا"}, format="json").status_code == 201
    )
    assert reviewer.post(f"/api/comments/{comment['id']}/resolve/").status_code == 403, (
        "only the program's editors resolve"
    )
    resolved = author.post(f"/api/comments/{comment['id']}/resolve/").json()
    assert resolved["status"] == "resolved" and resolved["resolved_by"]["email"] == "author@example.com"
    assert author.post(f"/api/comments/{comment['id']}/reopen/").status_code == 403, "authors do not reopen"
    reopened = reviewer.post(f"/api/comments/{comment['id']}/reopen/").json()
    assert reopened["status"] == "open" and reopened["resolved_by"] is None
    assert [r["body"] for r in reopened["replies"]] == ["عُدّل، شكرًا"]


def test_open_comments_follow_the_program_into_its_next_version(world):
    comment = create(login("reviewer@example.com"), world).json()
    with organization_context(world["org"]):
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
        lifecycle.transition(world["version"], S.WITHDRAWN, actor=world["owner"])
    listed = login("author@example.com").get(f"/api/programs/{world['program'].pk}/comments/").json()
    assert [(c["id"], c["status"], c["version"]) for c in listed] == [(comment["id"], "open", world["version"].pk)]


def test_comments_are_kept_out_of_other_organizations(world):
    other = Organization.objects.create(name="B", slug="b")
    with organization_context(other):
        member("outsider@example.com", Role.REVIEWER)
    comment = create(login("reviewer@example.com"), world).json()
    outsider = login("outsider@example.com")
    assert outsider.get(f"/api/comments/{comment['id']}/").status_code == 404
    with organization_context(world["org"]):
        assert Comment.objects.count() == 1
