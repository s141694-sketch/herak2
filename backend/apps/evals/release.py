"""The release gate (spec 5.5): an agent version runs for users only after it passed on the golden set."""

from .evaluation import current_thresholds
from .models import AgentEvaluation, GoldenSet

#: Evaluations made with these providers prove nothing about a real model.
NOT_EVIDENCE = {"fake", "recorded"}


def is_released(agent: str, prompt_version: str, model: str) -> bool:
    """Released when its latest golden set has a passing evaluation of this exact prompt version and model,
    made with a real provider against the thresholds the owner has set now."""
    golden = GoldenSet.objects.filter(agent=agent).order_by("-created_at", "-id").first()
    thresholds = current_thresholds(agent)
    if golden is None or not thresholds:
        return False
    return (
        AgentEvaluation.objects.filter(
            agent=agent, prompt_version=prompt_version, model=model, golden_set=golden, passed=True
        )
        .exclude(provider__in=NOT_EVIDENCE)
        .filter(thresholds=thresholds)
        .exists()
    )
