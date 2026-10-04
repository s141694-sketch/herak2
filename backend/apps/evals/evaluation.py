"""How each agent is evaluated, and the run that produces an AgentEvaluation (spec 5.5, 8.2).

An agent registers an ``EvaluatedAgent``: its gateway spec, the input columns of its golden set, the
labels experts may give, how to turn an item into the agent's payload and the agent's answer into a
label, and its metrics. ``run`` sends every item with an agreed label through the gateway's
evaluation path and stores the result, passed only if every metric the owner set a threshold for
reaches it.
"""

from collections.abc import Callable
from dataclasses import dataclass

from apps.ai.gateway import AgentSpec, AIUnavailable, Gateway

from . import metrics as m
from .models import AgentEvaluation, AgentThreshold, GoldenSet


@dataclass(frozen=True)
class EvaluatedAgent:
    spec: AgentSpec
    input_fields: tuple[str, ...]
    labels: tuple[str, ...]
    payload: Callable[[dict], dict]
    label_of: Callable[[dict], str]
    score: Callable[[list[str], list[str | None]], dict[str, float]]
    # For an answer whose label depends on what was asked too (an outline serving the competencies it was given).
    label_with_input: Callable[[dict, dict], str] | None = None

    @property
    def name(self) -> str:
        return self.spec.name

    def label(self, output: dict, payload: dict) -> str:
        if self.label_with_input is not None:
            return self.label_with_input(output, payload)
        return self.label_of(output)


def classification_score(gold, predicted):
    return {"accuracy": m.accuracy(gold, predicted)}


def detection_score(positive: str):
    def score(gold, predicted):
        return m.precision_recall(gold, predicted, positive)

    return score


REGISTRY: dict[str, EvaluatedAgent] = {}


def register(agent: EvaluatedAgent) -> EvaluatedAgent:
    REGISTRY[agent.name] = agent
    return agent


def current_thresholds(agent: str) -> dict[str, float]:
    return dict(AgentThreshold.objects.filter(agent=agent).values_list("metric", "minimum"))


def passes(scores: dict[str, float], thresholds: dict[str, float]) -> bool:
    """Every threshold met; no threshold at all means the owner has not decided, so nothing passes."""
    return bool(thresholds) and all(
        scores.get(metric, float("-inf")) >= minimum for metric, minimum in thresholds.items()
    )


def safe_payload(agent: EvaluatedAgent, item: dict) -> dict | None:
    """The agent's payload for a golden-set item, or None when the item cannot be read (it counts as unanswered,
    and the run goes on)."""
    try:
        return agent.payload(item)
    except Exception:  # noqa: BLE001 - one unreadable cell must not abort an evaluation
        return None


def run(agent: EvaluatedAgent, golden_set: GoldenSet, gateway: Gateway) -> AgentEvaluation:
    if golden_set.agent != agent.name:
        raise ValueError(f"golden set {golden_set.pk} is for {golden_set.agent}, not {agent.name}")
    items = list(golden_set.items.exclude(gold__isnull=True))
    if not items:
        raise ValueError("the golden set has no item with an agreed label")
    provider = gateway.provider_factory()
    if provider is None:
        raise AIUnavailable("not_configured")
    gold, predicted, unanswered = [], [], 0
    for item in items:
        gold.append(item.gold)
        payload = safe_payload(agent, item.input)
        if payload is None:
            predicted.append(None)
            unanswered += 1
            continue
        try:
            output = gateway.evaluate(agent.spec, payload, provider=provider)
        except AIUnavailable:
            predicted.append(None)
            unanswered += 1
        else:
            predicted.append(agent.label(output, payload))
    scores = {**agent.score(gold, predicted), "answered": 1 - unanswered / len(items)}
    thresholds = current_thresholds(agent.name)
    return AgentEvaluation.objects.create(
        agent=agent.name,
        prompt_version=agent.spec.prompt_version,
        model=provider.model,
        provider=provider.name,
        golden_set=golden_set,
        items=len(items),
        unanswered=unanswered,
        metrics={**scores, "confusion": m.confusion(gold, predicted)},
        thresholds=thresholds,
        passed=passes(scores, thresholds),
    )
