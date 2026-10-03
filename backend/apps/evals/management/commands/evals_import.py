import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.evals import golden

from ._agents import agent_named


class Command(BaseCommand):
    help = "Import a golden set filled in by experts (CSV: item_key, expert, label and the agent's input columns)."

    def add_arguments(self, parser):
        parser.add_argument("csv", type=Path)
        parser.add_argument("--agent", required=True)
        parser.add_argument("--name", required=True)

    def handle(self, *args, **options):
        agent = agent_named(options["agent"])
        try:
            golden_set = golden.import_set(agent, options["name"], options["csv"].read_text(encoding="utf-8"))
        except golden.GoldenSetError as exc:
            raise CommandError(str(exc)) from exc
        report = {"golden_set": golden_set.pk, **golden.agreement(golden_set)}
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
