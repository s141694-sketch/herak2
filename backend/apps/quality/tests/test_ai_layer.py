"""The AI layer of quality runs (tasks 4.6, D38, D42): where the rules are unsure, the classification agent
reads the objective; readings follow the content; failures leave the rules' report, marked partial."""

import json

import pytest

from apps.accounts.models import Organization, Role
from apps.ai import gateway as gw
from apps.ai import providers
from apps.ai.models import AICacheEntry, AIPolicy
from apps.ai.tests.fakes import FakeProvider, OpenGate, answer
from apps.programs import lifecycle, services
from apps.programs.models import ProgramVersion
from apps.programs.tests.factories import member, program
from apps.quality import services as quality
from apps.quality.models import Finding, QualityReport
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


def doc(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def reading(domain, level_id, verb="", explanation="قراءة"):
    return answer(
        json.dumps(
            {"domain": domain, "level_id": level_id, "verb": verb, "confidence": "medium", "explanation": explanation},
            ensure_ascii=False,
        )
    )


def verdict(value, explanation="شرح"):
    return answer(
        json.dumps({"verdict": value, "confidence": "medium", "explanation": explanation}, ensure_ascii=False)
    )


def suggestion(objective, explanation="اقتراح"):
    return answer(
        json.dumps({"objective": objective, "confidence": "medium", "explanation": explanation}, ensure_ascii=False)
    )


class Model(FakeProvider):
    """Answers by request content, so the order of calls does not matter.

    Classification: by objective text (``asked`` records them). Link checks: by (objective, competency code),
    "aligned" unless set. Suggestions: by competency code, a sound objective unless set (``suggested``)."""

    def __init__(self, answers):
        super().__init__(model="claude-opus-5-5")
        self.answers = answers
        self.asked = []
        self.links = {}
        self.suggestions = {}
        self.checked = []
        self.suggested = []

    def complete(self, request):
        payload = json.loads(request.user.removeprefix("<data>\n").removesuffix("\n</data>"))
        if "competency" in payload and "objective" in payload:
            key = (payload["objective"], payload["competency"]["code"])
            self.checked.append(key)
            outcome = self.links.get(key, verdict("aligned"))
        elif "competency" in payload:
            self.suggested.append(payload["competency"]["code"])
            outcome = self.suggestions.get(
                payload["competency"]["code"], suggestion("أن يطبق المتدرب إجراء العزل باستخدام قائمة التحقق بدقة")
            )
        else:
            self.asked.append(payload["objective"])
            outcome = self.answers[payload["objective"]]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


UNKNOWN = "أن يتأمل المتدرب تجربته"  # no dictionary verb: rule unclassified (low)
AMBIGUOUS = "أن يحدد المتدرب مخارج الطوارئ"  # يحدد sits on two levels: rule medium, level 1
CLEAR = "أن يطبق المتدرب الإجراء بدقة"  # high: never sent


@pytest.fixture
def world(monkeypatch, django_capture_on_commit_callbacks):
    model = Model({UNKNOWN: reading("affective", 3, "يتأمل"), AMBIGUOUS: reading("cognitive", 4, "يحدد")})
    monkeypatch.setattr(gw.gateway, "provider_factory", lambda: model)
    monkeypatch.setattr(gw.gateway, "release_gate", OpenGate())
    monkeypatch.setattr(gw.gateway, "sleep", lambda seconds: None)
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org), django_capture_on_commit_callbacks(execute=True):
        owner = member("author@example.com", Role.AUTHOR)
        prog = program(owner)
        version = prog.versions.get()
        root = services.add_node(version, title="البرنامج", actor=owner)
        blocks = {
            text: services.add_block(version, node=root, type="objective", actor=owner, content=doc(text))
            for text in (UNKNOWN, AMBIGUOUS, CLEAR)
        }
    return {"org": org, "owner": owner, "version": version, "blocks": blocks, "model": model}


def report(w):
    with organization_context(w["org"]):
        return QualityReport.objects.get(version=w["version"])


def analyses(w):
    with organization_context(w["org"]):
        return {a.text: a for a in report(w).objectives.all()}


def ai_findings(w):
    with organization_context(w["org"]):
        return {(f.kind, f.block_key): f for f in Finding.objects.filter(report__version=w["version"], source="ai")}


def test_unsure_objectives_get_the_agents_reading_and_sure_ones_are_never_sent(world):
    rows = analyses(world)
    assert (rows[UNKNOWN].ai_domain, rows[UNKNOWN].ai_level_id, rows[UNKNOWN].ai_level) == ("affective", 3, "التقييم")
    assert rows[AMBIGUOUS].ai_status == "done" and rows[CLEAR].ai_status == "none"
    assert CLEAR not in world["model"].asked
    state = report(world)
    assert (state.status, state.ai_state["status"]) == ("complete", "done")
    assert state.ai_prompts == {"classification": "2026-10-03.1", "alignment_suggestion": "2026-10-03.1"}
    assert state.ai_models == {"classification": "claude-opus-5-5", "alignment_suggestion": "claude-opus-5-5"}


def test_a_disagreement_is_shown_with_both_readings_at_low_confidence(world):
    found = ai_findings(world)
    unknown_key = world["blocks"][UNKNOWN].block_key
    ambiguous_key = world["blocks"][AMBIGUOUS].block_key
    suggestion = found[("bloom_ai_level", unknown_key)]
    assert (suggestion.severity, suggestion.confidence, suggestion.explanation) == ("info", "low", "قراءة")
    disagreement = found[("bloom_disagreement", ambiguous_key)]
    assert disagreement.params["rule"] == {"domain": "cognitive", "level_id": 1, "level": "تذكر"}
    assert disagreement.params["ai"]["level_id"] == 4 and disagreement.confidence == "low"


def test_readings_follow_the_content_and_unchanged_objectives_are_not_asked_again(
    world, django_capture_on_commit_callbacks
):
    asked = len(world["model"].asked)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_node(world["version"].nodes.get(), title="عنوان آخر", actor=world["owner"])
    assert len(world["model"].asked) == asked
    assert analyses(world)[UNKNOWN].ai_status == "done"
    world["model"].answers["أن يتأمل المتدرب تجربته في الموقع"] = reading("affective", 2)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_block(
            world["blocks"][UNKNOWN], content=doc("أن يتأمل المتدرب تجربته في الموقع"), actor=world["owner"]
        )
    assert world["model"].asked[asked:] == ["أن يتأمل المتدرب تجربته في الموقع"]


def test_a_failing_model_leaves_the_rules_report_marked_partial(world, django_capture_on_commit_callbacks):
    world["model"].answers["أن يتأمل المتدرب تجربة"] = providers.ProviderTimeout("timed out")
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_block(world["blocks"][UNKNOWN], content=doc("أن يتأمل المتدرب تجربة"), actor=world["owner"])
    state = report(world)
    assert (state.status, state.ai_state) == ("partial_rules_only", {"status": "partial", "reasons": ["timeout"]})
    with organization_context(world["org"]):
        assert Finding.objects.filter(report=state, kind="objective_unclassified").exists()


def test_rules_only_mode_is_a_complete_report(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]):
        AIPolicy.objects.create(mode=AIPolicy.Mode.RULES_ONLY)
        with django_capture_on_commit_callbacks(execute=True):
            services.update_block(world["blocks"][UNKNOWN], content=doc("أن يتأمل المتدرب"), actor=world["owner"])
    state = report(world)
    assert (state.status, state.ai_state) == ("complete", {"status": "skipped", "reasons": ["rules_only"]})
    assert ai_findings(world) == {}, "earlier AI results are not shown in rules-only mode"


def test_an_exhausted_quota_is_partial_and_says_why(world, django_capture_on_commit_callbacks, monkeypatch):
    monkeypatch.setattr(gw.sentry_sdk, "capture_message", lambda *a, **k: None)
    with organization_context(world["org"]):
        AIPolicy.objects.create(monthly_token_quota=1)
        with django_capture_on_commit_callbacks(execute=True):
            services.update_block(world["blocks"][UNKNOWN], content=doc("أن يتأمل المتدرب"), actor=world["owner"])
    state = report(world)
    assert (state.status, state.ai_state["reasons"]) == ("partial_rules_only", ["quota_exceeded"])


def test_a_dismissed_ai_finding_stays_dismissed(world, django_capture_on_commit_callbacks):
    key = world["blocks"][AMBIGUOUS].block_key
    with organization_context(world["org"]):
        quality.dismiss(
            ai_findings(world)[("bloom_disagreement", key)],
            reason="التحديد هنا تذكر",
            actor=world["owner"],
            role=Role.AUTHOR,
        )
        with django_capture_on_commit_callbacks(execute=True):
            services.update_node(world["version"].nodes.get(), title="عنوان", actor=world["owner"])
    assert ai_findings(world)[("bloom_disagreement", key)].dismissed_reason == "التحديد هنا تذكر"


def test_submission_waits_for_the_ai_layer_before_the_final_report(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        lifecycle.transition(world["version"], S.SUBMITTED, actor=world["owner"])
    state = report(world)
    assert (state.last_run, state.status, state.ai_state["status"]) == ("full", "complete", "done")


def test_a_superseded_ai_step_writes_nothing(world, django_capture_on_commit_callbacks):
    with organization_context(world["org"]):
        with django_capture_on_commit_callbacks(execute=False):
            stale = str(quality.request_run(world["version"], "full").run_id)
            quality.request_run(world["version"], "full")
        before = {k: (a.ai_status, a.ai_level_id) for k, a in analyses(world).items()}
        report_id = report(world).pk
    quality.run_ai(report_id, stale)
    assert {k: (a.ai_status, a.ai_level_id) for k, a in analyses(world).items()} == before


def test_an_edit_during_the_model_call_discards_the_late_answers(world, monkeypatch):
    from apps.quality import tasks

    monkeypatch.setattr(tasks.run_report, "apply_async", lambda *a, **k: None)
    with organization_context(world["org"]):
        run_id = str(quality.request_run(world["version"], "full").run_id)
        report_id = report(world).pk
        for row in report(world).objectives.all():
            row.ai_status = "none"
            row.save()
        AICacheEntry.objects.all().delete()  # otherwise the earlier answers come from the cache, not the model
    edited = {"done": False}
    original = world["model"].complete

    def answer_then_edit(request):
        if not edited["done"]:
            edited["done"] = True
            quality.request_run(world["version"], "light")
        return original(request)

    monkeypatch.setattr(world["model"], "complete", answer_then_edit)
    quality.run_ai(report_id, run_id)
    assert {a.ai_status for a in analyses(world).values()} == {"none"}
