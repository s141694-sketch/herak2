import json

from django.core.management.base import BaseCommand, CommandError

from apps.ai.gateway import AIUnavailable, gateway
from apps.evals import evaluation
from apps.evals.models import GoldenSet

from ._agents import agent_named


class Command(BaseCommand):
    help = "Evaluate the current version of an agent on its latest (or a given) golden set with the configured model."

    def add_arguments(self, parser):
        parser.add_argument("agent")
        parser.add_argument("--golden-set", type=int)

    def handle(self, *args, **options):
        agent = agent_named(options["agent"])
        sets = GoldenSet.objects.filter(agent=agent.name)
        golden_set = sets.filter(pk=options["golden_set"]).first() if options["golden_set"] else sets.first()
        if golden_set is None:
            raise CommandError(f"no golden set for {agent.name}")
        try:
            result = evaluation.run(agent, golden_set, gateway)
        except AIUnavailable as exc:
            if exc.reason == "not_configured":
                raise CommandError("no AI provider is configured: set ANTHROPIC_API_KEY (and AI_PROVIDER)") from exc
            raise CommandError(str(exc)) from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "evaluation": result.pk,
                    "agent": result.agent,
                    "prompt_version": result.prompt_version,
                    "model": result.model,
                    "provider": result.provider,
                    "items": result.items,
                    "unanswered": result.unanswered,
                    "metrics": result.metrics,
                    "thresholds": result.thresholds,
                    "passed": result.passed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
