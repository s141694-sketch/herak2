"""The pilot's measures of success for one organization (spec 1.6, task 8.6, D86): review rounds per program and
the time from the first draft to approval. Read only.

    python manage.py pilot_metrics --organization <slug> [--since YYYY-MM-DD] [--json]
"""

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Organization
from apps.tenancy.context import organization_context
from apps.workflows import metrics


class Command(BaseCommand):
    help = "Review rounds per program and the time from the first draft to approval, for one organization."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="the organization's slug")
        parser.add_argument("--since", type=date.fromisoformat, help="only programs first drafted on or after it")
        parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON instead of a table")

    def handle(self, *args, organization, since, as_json, **options):
        found = Organization.objects.filter(slug=organization).first()
        if found is None:
            raise CommandError(f"no organization {organization!r}")
        with organization_context(found):
            report = metrics.organization_measures(since=since)
        if as_json:
            report = {"organization": found.slug, "since": since.isoformat() if since else None, **report}
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self._table(report)

    def _table(self, report: dict) -> None:
        if not report["programs"]:
            self.stdout.write("no programs")
            return
        self.stdout.write("rounds  days   work days  approved  program")
        for m in report["programs"]:
            days = "-" if m["days"] is None else f"{m['days']:.1f}"
            work = "-" if m["work_days"] is None else str(m["work_days"])
            approved = "yes" if m["approved"] else "no"
            self.stdout.write(f"{m['rounds']:>6}  {days:>5}  {work:>9}  {approved:>8}  {m['title']}")
        s = report["summary"]
        self.stdout.write(
            f"\n{s['approved']} of {s['programs']} programs approved; "
            f"rounds: mean {s['rounds_mean']}, median {s['rounds_median']}; "
            f"to approval: median {s['days_median']} days, {s['work_days_median']} work days"
        )
