"""Drafting suggestions (task 4.8): asked for by an author, made by the drafting agent through the gateway, shown
only when Harak's rules accept them, and accepted or dismissed by the author, which is recorded (spec 5.5)."""

import json

import pytest
from django.dispatch import receiver
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role
from apps.agents.tests.test_drafting import SOUND, WEAK, outline_answer
from apps.ai import gateway as gw
from apps.ai import providers
from apps.ai.models import AIPolicy
from apps.ai.tests.fakes import FakeProvider, OpenGate, answer
from apps.audit.models import AuditLog
from apps.programs import lifecycle, services
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program, published_framework, published_template
from apps.suggestions.models import Suggestion
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


def doc(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


@pytest.fixture
def world():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        reviewer = member("reviewer@example.com", Role.REVIEWER)
        framework = published_framework(owner, codes=("FA-01", "EL-01"))
        template = published_template(
            owner, levels=[{"name_ar": "وحدة", "name_en": "Module"}, {"name_ar": "درس", "name_en": "Lesson"}]
        )
        version = program(owner, template=template, framework=framework).versions.get()
        root = services.add_node(version, title="الوحدة", actor=owner)
        weak = services.add_block(version, node=root, type="objective", content=doc(WEAK), actor=owner)
        sound = services.add_block(version, node=root, type="objective", content=doc(SOUND), actor=owner)
        note = services.add_block(version, node=root, type="content", content=doc("نص"), actor=owner)
        first_aid = framework.competencies.get(code="FA-01")
        services.link(version, kind="objective_competency", source=weak, competency=first_aid, actor=owner)
    return {
        "org": org,
        "owner": owner,
        "reviewer": reviewer,
        "version": version,
        "weak": weak,
        "sound": sound,
        "note": note,
        "first_aid": first_aid,
    }


@pytest.fixture
def ai(monkeypatch):
    """The gateway with a scripted provider and the release gate open (as after a passing evaluation)."""

    def use(*outcomes):
        provider = FakeProvider(model="claude-opus-5-5", script=list(outcomes))
        monkeypatch.setattr(gw.gateway, "provider_factory", lambda: provider)
        monkeypatch.setattr(gw.gateway, "release_gate", OpenGate())
        monkeypatch.setattr(gw.gateway, "sleep", lambda seconds: None)
        return provider

    return use


def signed_in(email="owner@example.com"):
    client = APIClient()
    assert client.post("/api/auth/login/", {"email": email, "password": "x" * 12}, format="json").status_code == 200
    return client


@pytest.fixture
def ask(django_capture_on_commit_callbacks):
    """Asks for a suggestion; the task queued on commit runs (eagerly in tests) before this returns."""

    def post(client, version, **body):
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(f"/api/program-versions/{version.pk}/suggestions/", body, format="json")

    return post


def rewrite_answer(text=SOUND):
    return answer(json.dumps({"objective": text, "confidence": "medium", "explanation": "أضفت فعلًا ملاحظًا."}))


# Rewrites.


def test_a_weak_objective_gets_a_rewrite_once_the_rules_accept_it(world, ai, ask):
    provider = ai(rewrite_answer())
    response = ask(signed_in(), world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    assert response.status_code == 202, response.content
    body = signed_in().get(f"/api/suggestions/{response.json()['id']}/").json()
    assert body["status"] == "ready" and body["kind"] == "rewrite"
    assert body["subject"] == str(world["weak"].block_key)
    assert body["original"] == WEAK
    assert body["result"]["objective"] == SOUND and body["result"]["confidence"] == "medium"
    assert body["model"] == "claude-opus-5-5" and body["prompt_version"]
    payload = json.loads(provider.requests[0].user.split("<data>")[1].split("</data>")[0])
    assert payload["objective"] == WEAK
    assert [c["code"] for c in payload["competencies"]] == ["FA-01"], "the competencies it is linked to"


def test_a_rewrite_the_rules_refuse_is_kept_but_never_shown(world, ai, ask):
    ai(rewrite_answer("أن يفهم المتدرب الإسعافات فهمًا عميقًا"))
    response = ask(signed_in(), world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    body = signed_in().get(f"/api/suggestions/{response.json()['id']}/").json()
    assert body["status"] == "rejected" and body["reason"] == "not_sound"
    assert body["result"] is None
    with organization_context(world["org"]):
        assert Suggestion.objects.get(pk=body["id"]).result["objective"].startswith("أن يفهم")


def test_a_sound_objective_or_another_block_is_not_sent(world, ai, ask):
    provider = ai()
    client = signed_in()
    sound = ask(client, world["version"], kind="rewrite", block_key=str(world["sound"].block_key))
    assert sound.status_code == 409 and sound.json()["error"]["code"] == "objective_already_sound"
    note = ask(client, world["version"], kind="rewrite", block_key=str(world["note"].block_key))
    assert note.status_code == 409 and note.json()["error"]["code"] == "suggestion_subject_invalid"
    missing = ask(client, world["version"], kind="rewrite", block_key="11111111-1111-4111-8111-111111111111")
    assert missing.status_code == 409 and missing.json()["error"]["code"] == "suggestion_subject_invalid"
    assert ask(client, world["version"], kind="rewrite").status_code == 400
    assert provider.requests == []


def test_the_rows_are_refreshed_from_the_live_document_before_reading_them(world, ai, ask):
    ai(rewrite_answer())
    seen = []

    @receiver(lifecycle.rows_requested, weak=False)
    def note(sender, version, **kwargs):
        seen.append(version.pk)

    try:
        ask(signed_in(), world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    finally:
        lifecycle.rows_requested.disconnect(note)
    assert seen == [world["version"].pk]


def test_the_same_request_while_one_is_open_is_not_sent_twice(world, ai, ask):
    provider = ai(rewrite_answer())
    client = signed_in()
    first = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    second = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    assert second["id"] == first["id"] and len(provider.requests) == 1


def test_when_no_ai_answers_the_reason_is_recorded(world, ai, monkeypatch, ask):
    with organization_context(world["org"]):
        AIPolicy.objects.create(mode=AIPolicy.Mode.RULES_ONLY)
    ai()
    response = ask(signed_in(), world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    body = signed_in().get(f"/api/suggestions/{response.json()['id']}/").json()
    assert body["status"] == "failed" and body["reason"] == "rules_only"
    with organization_context(world["org"]):
        AIPolicy.objects.all().delete()
    timeout = providers.ProviderTimeout("timed out")
    ai(timeout, timeout, timeout)
    response = ask(signed_in(), world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    assert signed_in().get(f"/api/suggestions/{response.json()['id']}/").json()["reason"] == "timeout"


# Outlines.


def test_an_outline_is_drafted_from_the_target_competencies(world, ai, ask):
    with organization_context(world["org"]):
        world["version"].targets.exclude(competency=world["first_aid"]).delete()
    provider = ai(answer(json.dumps(outline_answer())))
    response = ask(signed_in(), world["version"], kind="outline")
    assert response.status_code == 202
    body = signed_in().get(f"/api/suggestions/{response.json()['id']}/").json()
    assert body["status"] == "ready"
    assert [n["title"] for n in body["result"]["nodes"]] == ["السلامة في الموقع", "الإسعافات الأولية"]
    [objective] = body["result"]["objectives"]
    assert objective["competency"] == "FA-01"
    assert objective["competency_key"] == str(world["first_aid"].competency_key)
    payload = json.loads(provider.requests[0].user.split("<data>")[1].split("</data>")[0])
    assert payload["levels"] == ["وحدة", "درس"]
    assert payload["programme"] == {"title": "برنامج السلامة", "target_role": "فني سلامة"}
    assert [c["code"] for c in payload["competencies"]] == ["FA-01"]


def test_an_outline_needs_target_competencies(world, ai, ask):
    with organization_context(world["org"]):
        world["version"].targets.all().delete()
    response = ask(signed_in(), world["version"], kind="outline")
    assert response.status_code == 409 and response.json()["error"]["code"] == "no_target_competencies"


def test_an_outline_with_nothing_usable_is_rejected(world, ai, ask):
    ai(answer(json.dumps(outline_answer(objectives=[{"node": "l1", "competency": "FA-01", "text": WEAK}]))))
    response = ask(signed_in(), world["version"], kind="outline")
    body = signed_in().get(f"/api/suggestions/{response.json()['id']}/").json()
    assert body["status"] == "rejected" and body["reason"] == "nothing_usable"


# Decisions.


def test_accepting_and_dismissing_are_recorded_once(world, ai, ask):
    ai(rewrite_answer(), rewrite_answer())
    client = signed_in()
    first = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    accepted = client.post(f"/api/suggestions/{first['id']}/accept/")
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    assert accepted.json()["decided_by"]["email"] == "owner@example.com" and accepted.json()["decided_at"]
    again = client.post(f"/api/suggestions/{first['id']}/dismiss/", {"reason": "x"}, format="json")
    assert again.status_code == 409 and again.json()["error"]["code"] == "suggestion_not_open"

    with organization_context(world["org"]):
        Suggestion.objects.filter(pk=first["id"]).delete()
    second = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    dismissed = client.post(f"/api/suggestions/{second['id']}/dismiss/", {"reason": "غيّر المعنى"}, format="json")
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    assert dismissed.json()["decision_reason"] == "غيّر المعنى"
    too_long = client.post(f"/api/suggestions/{second['id']}/dismiss/", {"reason": "ط" * 1001}, format="json")
    assert too_long.status_code in (400, 409)
    with organization_context(world["org"]):
        events = list(AuditLog.objects.filter(event__startswith="ai_suggestion.").values_list("event", flat=True))
    assert sorted(events) == ["ai_suggestion.accepted", "ai_suggestion.dismissed"]


def test_a_rejected_or_failed_suggestion_cannot_be_accepted(world, ai, ask):
    ai(rewrite_answer(WEAK))
    client = signed_in()
    rejected = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    response = client.post(f"/api/suggestions/{rejected['id']}/accept/")
    assert response.status_code == 409 and response.json()["error"]["code"] == "suggestion_not_open"


def test_a_late_answer_never_reopens_a_dismissed_suggestion(world, ai, monkeypatch, ask):
    from apps.suggestions import services as suggestion_services

    monkeypatch.setattr(suggestion_services, "_enqueue", lambda suggestion: None)
    client = signed_in()
    pending = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    assert pending["status"] == "pending"
    assert client.post(f"/api/suggestions/{pending['id']}/dismiss/", {}, format="json").status_code == 200
    ai(rewrite_answer())
    with organization_context(world["org"]):
        suggestion_services.run(pending["id"])
        assert Suggestion.objects.get(pk=pending["id"]).status == Suggestion.Status.DISMISSED


def test_only_the_programs_editors_ask_and_decide(world, ai, ask):
    ai(rewrite_answer())
    reviewer = signed_in("reviewer@example.com")
    refused = ask(reviewer, world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    assert refused.status_code == 403
    made = ask(signed_in(), world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    assert reviewer.post(f"/api/suggestions/{made['id']}/accept/").status_code == 403
    assert reviewer.get(f"/api/program-versions/{world['version'].pk}/suggestions/").status_code == 200


def test_a_version_that_left_draft_takes_no_suggestion_or_decision(world, ai, ask):
    ai(rewrite_answer())
    client = signed_in()
    made = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    with organization_context(world["org"]):
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    asked = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key))
    assert asked.status_code == 409 and asked.json()["error"]["code"] == "version_locked"
    accepted = client.post(f"/api/suggestions/{made['id']}/accept/")
    assert accepted.status_code == 409 and accepted.json()["error"]["code"] == "version_locked"


def test_the_versions_suggestions_are_listed_newest_first(world, ai, ask):
    ai(rewrite_answer(), answer(json.dumps(outline_answer())))
    client = signed_in()
    rewrite = ask(client, world["version"], kind="rewrite", block_key=str(world["weak"].block_key)).json()
    outline = ask(client, world["version"], kind="outline").json()
    listed = client.get(f"/api/program-versions/{world['version'].pk}/suggestions/").json()
    assert [s["id"] for s in listed] == [outline["id"], rewrite["id"]]
