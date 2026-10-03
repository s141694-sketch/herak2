"""The alignment part of the AI layer (task 4.7): a link's meaning, and suggested objectives for target
competencies no objective serves; judgements are kept while their inputs hold."""

import pytest

from apps.ai import gateway as gw
from apps.ai.gateway import ReleaseGate
from apps.ai.models import AICacheEntry
from apps.programs import services
from apps.quality.models import AICheck, Finding
from apps.tenancy.context import organization_context

from .test_ai_layer import CLEAR, ai_findings, doc, report, suggestion, verdict, world  # noqa: F401

pytestmark = pytest.mark.django_db


def competencies(w):
    with organization_context(w["org"]):
        return list(w["version"].targets.select_related("competency").order_by("competency__order"))


def link(w, block_text, target, capture):
    with organization_context(w["org"]), capture(execute=True):
        services.link(
            w["version"],
            kind="objective_competency",
            source=w["blocks"][block_text],
            actor=w["owner"],
            competency=target.competency,
        )


def test_every_target_no_objective_serves_gets_a_sound_suggested_objective(world):  # noqa: F811
    with organization_context(world["org"]):
        found = list(Finding.objects.filter(report__version=world["version"], kind="competency_objective_suggestion"))
    assert {f.competency_id for f in found} == {t.competency_id for t in competencies(world)}
    one = found[0]
    assert one.severity == "info" and one.params["objective"].startswith("أن يطبق المتدرب")
    assert one.explanation == "اقتراح"


def test_a_suggestion_harak_rules_refuse_is_kept_out_and_not_asked_again(world, django_capture_on_commit_callbacks):  # noqa: F811
    first, second = competencies(world)
    code = first.competency.code
    with organization_context(world["org"]):
        AICheck.objects.filter(subject=str(first.competency.competency_key)).delete()
        AICacheEntry.objects.filter(agent="alignment_suggestion").delete()
    world["model"].suggestions[code] = suggestion("أن يفهم المتدرب أهمية الكفاية")
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_node(world["version"].nodes.get(), title="عنوان", actor=world["owner"])
    with organization_context(world["org"]):
        assert AICheck.objects.get(subject=str(first.competency.competency_key)).status == "rejected"
    with organization_context(world["org"]):
        suggested = set(
            Finding.objects.filter(
                report__version=world["version"], kind="competency_objective_suggestion"
            ).values_list("competency__code", flat=True)
        )
    assert code not in suggested and second.competency.code in suggested
    asked = world["model"].suggested.count(code)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_node(world["version"].nodes.get(), title="عنوان آخر", actor=world["owner"])
    assert world["model"].suggested.count(code) == asked


def test_a_misaligned_link_is_a_warning_and_its_competency_no_longer_gets_a_suggestion(
    world,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    target = competencies(world)[0]
    world["model"].links[(CLEAR, target.competency.code)] = verdict("misaligned", "الهدف لا يخدم هذه الكفاية")
    link(world, CLEAR, target, django_capture_on_commit_callbacks)
    found = ai_findings(world)
    mismatch = [f for (kind, _), f in found.items() if kind == "link_semantic_mismatch"]
    assert len(mismatch) == 1
    assert (mismatch[0].severity, mismatch[0].block_key, mismatch[0].competency_id) == (
        "warning",
        world["blocks"][CLEAR].block_key,
        target.competency_id,
    )
    assert mismatch[0].explanation == "الهدف لا يخدم هذه الكفاية"
    suggested_for = {f.competency_id for (kind, _), f in found.items() if kind == "competency_objective_suggestion"}
    assert target.competency_id not in suggested_for


def test_a_weak_link_is_information(world, django_capture_on_commit_callbacks):  # noqa: F811
    target = competencies(world)[1]
    world["model"].links[(CLEAR, target.competency.code)] = verdict("weak")
    link(world, CLEAR, target, django_capture_on_commit_callbacks)
    assert [f.severity for (kind, _), f in ai_findings(world).items() if kind == "link_semantic_weak"] == ["info"]


def test_a_link_is_judged_again_only_when_its_objective_changes(world, django_capture_on_commit_callbacks):  # noqa: F811
    target = competencies(world)[0]
    link(world, CLEAR, target, django_capture_on_commit_callbacks)
    checked = len(world["model"].checked)
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_node(world["version"].nodes.get(), title="عنوان", actor=world["owner"])
    assert len(world["model"].checked) == checked
    with organization_context(world["org"]), django_capture_on_commit_callbacks(execute=True):
        services.update_block(
            world["blocks"][CLEAR], content=doc("أن يطبق المتدرب الإجراء بإتقان"), actor=world["owner"]
        )
    assert world["model"].checked[checked:] == [("أن يطبق المتدرب الإجراء بإتقان", target.competency.code)]


class OnlyClassification(ReleaseGate):
    def is_released(self, spec, model):
        return spec.name == "classification"


def test_each_part_runs_only_once_released(world, monkeypatch, django_capture_on_commit_callbacks):  # noqa: F811
    monkeypatch.setattr(gw.gateway, "release_gate", OnlyClassification())
    with organization_context(world["org"]):
        AICheck.objects.all().delete()
        with django_capture_on_commit_callbacks(execute=True):
            services.update_node(world["version"].nodes.get(), title="عنوان", actor=world["owner"])
    kinds = {kind for kind, _ in ai_findings(world)}
    assert "competency_objective_suggestion" not in kinds and "bloom_ai_level" in kinds
    assert report(world).ai_state == {"status": "done", "reasons": []}
