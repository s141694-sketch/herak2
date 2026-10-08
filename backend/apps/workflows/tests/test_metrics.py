"""The pilot's measures of success (spec 1.6, task 8.6, D86): review rounds per program and the time from the
first draft to approval, read from Harak's own records."""

import json
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import Organization, Role
from apps.programs import services as programs
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context
from apps.workflows import metrics, services

from .factories import two_stage_template
from .test_workflow import claim_and_decide, draft_of

pytestmark = pytest.mark.django_db
MUSCAT = ZoneInfo("Asia/Muscat")


def at(day, hour=9):
    """A moment in October 2026, Muscat time: 4 Oct is a Sunday, a work day (Sunday to Thursday)."""
    return datetime(2026, 10, day, hour, tzinfo=MUSCAT)


@pytest.fixture
def clock(monkeypatch):
    """Sets the time the next records are made at."""

    def set_to(moment):
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)

    return set_to


@pytest.fixture
def world(clock):
    org = Organization.objects.create(name="A", slug="a", work_days=[6, 0, 1, 2, 3])
    with organization_context(org):
        people = {
            "admin": member("admin@example.com", Role.ADMIN),
            "author": member("author@example.com", Role.AUTHOR),
            "reviewer": member("reviewer@example.com", Role.REVIEWER),
            "approver": member("approver@example.com", Role.APPROVER),
        }
        two_stage_template(people["admin"], approver=people["approver"])
        yield {"org": org, **people}


def new_program(world, title):
    version = program(world["author"], title=title, targets=[]).versions.get()
    programs.add_node(version, title="الوحدة", actor=world["author"])
    return version


def submit(world, version):
    return services.submit(version, actor=world["author"], role=Role.AUTHOR)


def approve_both_stages(world, version):
    claim_and_decide(world, world["reviewer"], "approve", version=version)
    return claim_and_decide(world, world["approver"], "approve", version=version)


def test_a_program_approved_after_one_return_took_two_rounds(world, clock):
    clock(at(4))  # Sunday: the first draft
    first = new_program(world, "السلامة")
    clock(at(5))
    submit(world, first)
    clock(at(6))
    returned = claim_and_decide(world, world["reviewer"], "return", note="أكمل التقويم", version=first)
    clock(at(7))
    second = submit(world, draft_of(returned))
    clock(at(11, 14))  # the next Sunday, past the weekend (Friday and Saturday)
    approve_both_stages(world, second)

    [measure] = metrics.organization_measures()["programs"]
    assert measure["title"] == "السلامة"
    assert measure["rounds"] == 2
    assert measure["approved"] is True
    # 4 Oct 09:00 to 11 Oct 14:00: 7.2 days; the work days after the first are 5 to 8 and 11 Oct.
    assert measure["days"] == 7.2
    assert measure["work_days"] == 5


def test_withdrawn_and_cancelled_submissions_are_not_rounds(world, clock):
    clock(at(4))
    version = new_program(world, "برنامج")
    submit(world, version)
    withdrawn = services.withdraw(version, actor=world["author"], role=Role.AUTHOR)
    again = submit(world, draft_of(withdrawn))
    approve_both_stages(world, again)
    # Another program: its submission cancelled by an admin, then a new version approved.
    cancelled = services.cancel(submit(world, new_program(world, "برنامج ملغى")), actor=world["admin"], role=Role.ADMIN)
    revision = programs.start_new_version(cancelled.program, actor=world["admin"])
    approve_both_stages(world, submit(world, revision))

    rounds = {m["title"]: m["rounds"] for m in metrics.organization_measures()["programs"]}
    assert rounds == {"برنامج": 1, "برنامج ملغى": 1}


def test_a_program_still_in_review_counts_its_rounds_so_far(world, clock):
    clock(at(4))
    version = new_program(world, "قيد المراجعة")
    submit(world, version)
    returned = claim_and_decide(world, world["reviewer"], "return", note="أعد", version=version)
    submit(world, draft_of(returned))

    [measure] = metrics.organization_measures()["programs"]
    assert (measure["rounds"], measure["approved"], measure["days"], measure["work_days"]) == (1, False, None, None)


def test_a_later_revision_does_not_change_the_first_cycle(world, clock):
    clock(at(4))
    version = new_program(world, "برنامج معتمد")
    clock(at(5))
    approved = approve_both_stages(world, submit(world, version))
    clock(at(20))  # months later in practice: a revision of the approved program, returned once
    revision = programs.start_new_version(approved.program, actor=world["admin"])
    claim_and_decide(world, world["reviewer"], "return", note="أعد", version=submit(world, revision))

    [measure] = metrics.organization_measures()["programs"]
    assert measure["rounds"] == 1
    assert datetime.fromisoformat(measure["approved_at"]) == at(5)


def test_the_summary_is_over_approved_programs_in_the_period(world, clock):
    for day, title, returns in ((4, "أ", 0), (5, "ب", 2), (6, "ج", 1)):
        clock(at(day))
        version = new_program(world, title)
        for _ in range(returns):
            submit(world, version)
            version = draft_of(claim_and_decide(world, world["reviewer"], "return", note="أعد", version=version))
        submit(world, version)
        clock(at(day + 7))
        approve_both_stages(world, version)
    clock(at(20))
    new_program(world, "مسودة فقط")

    everything = metrics.organization_measures()
    assert everything["summary"] == {
        "programs": 4,
        "approved": 3,
        "rounds_mean": 2.0,
        "rounds_median": 2,
        "days_median": 7.0,
        "work_days_median": 5,
    }
    # The pilot's programs: those whose first draft is on or after the day it started.
    since = metrics.organization_measures(since=at(5).date())
    assert [m["title"] for m in since["programs"]] == ["ب", "ج", "مسودة فقط"]
    assert (since["summary"]["approved"], since["summary"]["rounds_mean"]) == (2, 2.5)


def test_the_command_reads_one_organization_only(world, clock):
    clock(at(4))
    approve_both_stages(world, submit(world, new_program(world, "برنامج المؤسسة")))
    other = Organization.objects.create(name="B", slug="b")
    with organization_context(other):
        member("other-author@example.com", Role.AUTHOR)

    out = StringIO()
    call_command("pilot_metrics", "--organization", "a", "--json", stdout=out)
    report = json.loads(out.getvalue())
    assert report["organization"] == "a"
    assert [m["title"] for m in report["programs"]] == ["برنامج المؤسسة"]
    assert report["summary"]["approved"] == 1

    out = StringIO()
    call_command("pilot_metrics", "--organization", "b", stdout=out)
    assert "no programs" in out.getvalue()

    with pytest.raises(CommandError):
        call_command("pilot_metrics", "--organization", "missing")
