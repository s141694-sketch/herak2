from django.core.management.base import BaseCommand

from apps.evals.models import AgentThreshold


class Command(BaseCommand):
    help = "Set the owner's minimum for one metric of an agent (spec 5.5). Changing it requires a new evaluation."

    def add_arguments(self, parser):
        parser.add_argument("agent")
        parser.add_argument("metric")
        parser.add_argument("minimum", type=float)
        parser.add_argument("--note", default="")

    def handle(self, *args, **options):
        threshold, _ = AgentThreshold.objects.update_or_create(
            agent=options["agent"],
            metric=options["metric"],
            defaults={"minimum": options["minimum"], "note": options["note"]},
        )
        self.stdout.write(str(threshold))
