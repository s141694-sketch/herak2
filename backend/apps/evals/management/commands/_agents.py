from django.core.management.base import CommandError

from apps.evals.evaluation import REGISTRY, EvaluatedAgent


def agent_named(name: str) -> EvaluatedAgent:
    try:
        import apps.agents  # noqa: F401 - registers the agents with the evaluation registry
    except ModuleNotFoundError:
        pass
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY)) or "none yet"
        raise CommandError(f"unknown agent {name!r}; registered agents: {known}")
    return REGISTRY[name]
