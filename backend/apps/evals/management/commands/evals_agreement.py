import json

from django.core.management.base import BaseCommand, CommandError

from apps.evals import golden
from apps.evals.models import GoldenSet


class Command(BaseCommand):
    help = "Expert agreement on a golden set: the realistic ceiling for an agent (spec 8.2)."

    def add_arguments(self, parser):
        parser.add_argument("golden_set", type=int)

    def handle(self, *args, **options):
        golden_set = GoldenSet.objects.filter(pk=options["golden_set"]).first()
        if golden_set is None:
            raise CommandError("no such golden set")
        self.stdout.write(json.dumps(golden.agreement(golden_set), ensure_ascii=False, indent=2))
