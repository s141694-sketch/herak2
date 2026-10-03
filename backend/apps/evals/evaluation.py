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

    @property
    def name(self) -> str:
        return self.spec.name


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
        try:
            output = gateway.evaluate(agent.spec, agent.payload(item.input), provider=provider)
        except AIUnavailable:
            predicted.append(None)
            unanswered += 1
        else:
            predicted.append(agent.label_of(output))
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
