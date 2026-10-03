"""Golden set import, expert agreement, evaluation runs and the release gate (task 4.5, spec 5.5 and 8.2)."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Organization
from apps.ai.gateway import Gateway, ReleaseGate
from apps.ai.models import AIUsage
from apps.ai.tests.fakes import FakeProvider, answer
from apps.evals import evaluation, golden, release
from apps.evals.models import AgentEvaluation, AgentThreshold, GoldenItem
from apps.tenancy.context import organization_context

from .toy import CSV, TOY

pytestmark = pytest.mark.django_db


@pytest.fixture
def toy_registered():
    evaluation.register(TOY)
    yield TOY
    evaluation.REGISTRY.pop(TOY.name, None)


def provider(*levels, name="claude"):
    fake = FakeProvider(model="claude-opus-5-5", script=[answer(json.dumps({"level_id": level})) for level in levels])
    fake.name = name
    return fake


def run_with(fake):
    return evaluation.run(
        TOY, golden.import_set(TOY, "أولى", CSV), Gateway(provider_factory=lambda: fake, sleep=lambda s: None)
    )


def test_the_agreed_label_is_the_adjudicators_or_the_majority_and_a_tie_has_none():
    golden_set = golden.import_set(TOY, "أولى", CSV)
    gold = dict(GoldenItem.objects.filter(golden_set=golden_set).values_list("item_key", "gold"))
    assert gold == {"o1": "1", "o2": "3", "o3": None, "o4": "6"}


@pytest.mark.parametrize(
    ("csv_text", "message"),
    [
        ("item_key,expert,label\no1,a,1\n", "missing columns: objective"),
        ("item_key,objective,expert,label\no1,x,a,7\n", "label '7' is not one of"),
        ("item_key,objective,expert,label\no1,x,a,1\no1,y,b,1\n", "different input"),
        ("item_key,objective,expert,label\no1,x,a,1\no1,x,a,2\n", "labelled item o1 twice"),
        ("item_key,objective,expert,label\n", "no rows"),
    ],
)
def test_malformed_golden_sets_are_refused_with_the_line(csv_text, message):
    with pytest.raises(golden.GoldenSetError, match=message):
        golden.parse(TOY, csv_text)


def test_expert_agreement_is_reported_as_the_ceiling():
    report = golden.agreement(golden.import_set(TOY, "أولى", CSV))
    assert report["items"] == 4 and report["without_agreed_label"] == 1
    assert set(report["cohen_kappa"]) == {"khalid~mazen", "khalid~sara", "mazen~sara"}
    assert report["percent_agreement"] == pytest.approx((1 + 1 / 3 + 0 + 0) / 4)
    assert "fleiss_kappa" not in report  # o4 has two experts besides the adjudicator, the others three


def test_a_run_scores_the_items_with_an_agreed_label_and_needs_the_owners_thresholds():
    result = run_with(provider(1, 3, 5))
    assert (result.items, result.unanswered, result.provider, result.model) == (3, 0, "claude", "claude-opus-5-5")
    assert result.metrics["accuracy"] == pytest.approx(2 / 3)
    assert result.metrics["confusion"] == {"1": {"1": 1}, "3": {"3": 1}, "6": {"5": 1}}
    assert result.passed is False and result.thresholds == {}


def test_a_run_passes_only_when_every_threshold_is_met():
    AgentThreshold.objects.create(agent="toy_level", metric="accuracy", minimum=0.6)
    AgentThreshold.objects.create(agent="toy_level", metric="answered", minimum=1.0)
    assert run_with(provider(1, 3, 5)).passed is True
    AgentThreshold.objects.filter(metric="accuracy").update(minimum=0.9)
    assert run_with(provider(1, 3, 5)).passed is False


def test_unanswered_items_count_as_wrong_and_lower_the_answered_share():
    fake = FakeProvider(
        model="claude-opus-5-5",
        script=[answer('{"level_id": 1}'), answer("x"), answer("x"), answer("x"), answer('{"level_id": 6}')],
    )
    fake.name = "claude"
    result = run_with(fake)
    assert result.unanswered == 1 and result.metrics["answered"] == pytest.approx(2 / 3)
    assert result.metrics["confusion"]["3"] == {"none": 1}


def test_evaluation_calls_touch_no_organization_data():
    run_with(provider(1, 3, 6))
    assert not AIUsage.all_organizations.exists()


def test_the_release_gate_opens_only_for_the_exact_version_that_passed_with_a_real_model():
    spec = TOY.spec
    assert not release.is_released("toy_level", "v1", "claude-opus-5-5")
    AgentThreshold.objects.create(agent="toy_level", metric="accuracy", minimum=0.6)
    run_with(provider(1, 3, 6, name="recorded"))
    assert not release.is_released("toy_level", "v1", "claude-opus-5-5")
    run_with(provider(1, 3, 6))
    assert release.is_released("toy_level", "v1", "claude-opus-5-5")
    assert ReleaseGate().is_released(spec, "claude-opus-5-5")
    assert not release.is_released("toy_level", "v2", "claude-opus-5-5")
    assert not release.is_released("toy_level", "v1", "claude-sonnet-5-5")
    AgentThreshold.objects.filter(metric="accuracy").update(minimum=0.65)
    assert not release.is_released("toy_level", "v1", "claude-opus-5-5")


def test_a_newer_golden_set_needs_a_new_evaluation():
    AgentThreshold.objects.create(agent="toy_level", metric="accuracy", minimum=0.6)
    run_with(provider(1, 3, 6))
    assert release.is_released("toy_level", "v1", "claude-opus-5-5")
    golden.import_set(TOY, "ثانية", CSV)
    assert not release.is_released("toy_level", "v1", "claude-opus-5-5")


def test_the_gateway_uses_the_released_version_for_organizations():
    AgentThreshold.objects.create(agent="toy_level", metric="accuracy", minimum=0.6)
    run_with(provider(1, 3, 6))
    org = Organization.objects.create(name="A", slug="a")
    fake = provider(4)
    with organization_context(org):
        result = Gateway(provider_factory=lambda: fake).call(TOY.spec, {"objective": "أن يحلل"}, organization_id=org.pk)
    assert result.output == {"level_id": 4}


def test_commands_import_report_set_thresholds_and_refuse_unknown_agents(tmp_path, toy_registered, capsys):
    path = tmp_path / "golden.csv"
    path.write_text(CSV, encoding="utf-8")
    call_command("evals_import", str(path), agent="toy_level", name="أولى")
    imported = json.loads(capsys.readouterr().out)
    assert imported["items"] == 4
    call_command("evals_agreement", str(imported["golden_set"]))
    assert json.loads(capsys.readouterr().out)["without_agreed_label"] == 1
    call_command("evals_threshold", "toy_level", "accuracy", "0.8", note="قرار المالك")
    assert AgentThreshold.objects.get().minimum == 0.8
    with pytest.raises(CommandError, match="unknown agent"):
        call_command("evals_import", str(path), agent="nobody", name="x")
    with pytest.raises(CommandError, match="no AI provider is configured"):
        call_command("evals_run", "toy_level")
    assert not AgentEvaluation.objects.exists()
