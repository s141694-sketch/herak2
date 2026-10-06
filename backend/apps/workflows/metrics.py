"""The pilot's measures of success (spec 1.6, task 8.6, D86), read from Harak's own records.

- A review round is a submission that ended with a decision: returned or approved. A withdrawn or cancelled
  submission had no decision, so it is not a round.
- The time to approval runs from the creation of the program's first version (its first draft) to its first
  approval, in days and in the organization's work days.

The baseline form used at the client before Harak asks for the same two things, so the two can be compared.
Read only: nothing here writes.
"""

from datetime import date, datetime, timedelta
from statistics import mean, median

from django.utils import timezone

from apps.accounts.models import Organization
from apps.programs.models import Program, ProgramVersion
from apps.tenancy.context import current_organization_id

from .models import WorkflowInstance

DECIDED = (WorkflowInstance.Outcome.APPROVED, WorkflowInstance.Outcome.RETURNED)


def work_days_between(start: datetime, end: datetime, work_days) -> int:
    """The organization's work days after the day of ``start``, up to and including the day of ``end``."""
    week = set(work_days)
    first, last = timezone.localtime(start).date(), timezone.localtime(end).date()
    return sum(1 for n in range(1, (last - first).days + 1) if (first + timedelta(days=n)).weekday() in week)


def program_measure(program: Program, work_days) -> dict:
    versions = ProgramVersion.objects.filter(program=program)
    started_at = min(v.created_at for v in versions)
    approved_at = min((v.approved_at for v in versions if v.approved_at is not None), default=None)
    rounds = WorkflowInstance.objects.filter(version__program=program, outcome__in=DECIDED)
    if approved_at is not None:
        rounds = rounds.filter(created_at__lte=approved_at)
    measure = {
        "id": program.pk,
        "title": program.title,
        "rounds": rounds.count(),
        "approved": approved_at is not None,
        "started_at": started_at.isoformat(),
        "approved_at": approved_at.isoformat() if approved_at else None,
        "days": None,
        "work_days": None,
    }
    if approved_at is not None:
        measure["days"] = round((approved_at - started_at).total_seconds() / 86400, 1)
        measure["work_days"] = work_days_between(started_at, approved_at, work_days)
    return measure


def summary(measures: list[dict]) -> dict:
    approved = [m for m in measures if m["approved"]]
    result = {
        "programs": len(measures),
        "approved": len(approved),
        "rounds_mean": None,
        "rounds_median": None,
        "days_median": None,
        "work_days_median": None,
    }
    if approved:
        result["rounds_mean"] = round(mean(m["rounds"] for m in approved), 1)
        result["rounds_median"] = median(m["rounds"] for m in approved)
        result["days_median"] = median(m["days"] for m in approved)
        result["work_days_median"] = median(m["work_days"] for m in approved)
    return result


def organization_measures(*, since: date | None = None) -> dict:
    """Every program of the active organization, oldest first; with ``since``, only the programs whose first
    draft was made on or after that day (the pilot's programs)."""
    organization = Organization.objects.get(pk=current_organization_id())
    measures = [program_measure(p, organization.work_days) for p in Program.objects.all()]
    if since is not None:
        measures = [m for m in measures if timezone.localtime(datetime.fromisoformat(m["started_at"])).date() >= since]
    measures.sort(key=lambda m: (m["started_at"], m["id"]))
    return {"programs": measures, "summary": summary(measures)}
