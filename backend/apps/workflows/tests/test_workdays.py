"""Due dates in the organization's work days (spec 6.3, task 5.6, D58)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.workflows.workdays import add_work_days, subtract_work_days

MUSCAT = ZoneInfo("Asia/Muscat")
SUN_TO_THU = [6, 0, 1, 2, 3]  # Python weekdays: Monday=0


def at(day, hour=10, minute=0):
    # October 2026: the 4th is a Sunday.
    return datetime(2026, 10, day, hour, minute, tzinfo=MUSCAT)


@pytest.mark.parametrize(
    "start,days,due",
    [
        (at(4), 0, at(4)),  # no time allowed: due on entry
        (at(4), 1, at(5)),  # Sunday + 1 = Monday, same time
        (at(4), 4, at(8)),  # Sunday + 4 = Thursday
        (at(7), 2, at(11)),  # Wednesday + 2 skips Friday and Saturday: Sunday
        (at(8, 23, 30), 1, at(11, 23, 30)),  # Thursday late evening + 1 = Sunday
        (at(9), 1, at(12, 0)),  # entered on a Friday: counted from Sunday's start
        (at(10, 15), 0, at(11, 0)),  # Saturday with no time: the start of Sunday
    ],
)
def test_work_days_are_added_skipping_days_off(start, days, due):
    assert add_work_days(start, days, SUN_TO_THU) == due


def test_the_result_is_in_the_platform_time_zone_whatever_the_input():
    start_utc = at(7).astimezone(ZoneInfo("UTC"))
    assert add_work_days(start_utc, 2, SUN_TO_THU) == at(11)


def test_another_week_is_respected():
    mon_to_fri = [0, 1, 2, 3, 4]
    assert add_work_days(at(8), 1, mon_to_fri) == at(9)  # Thursday + 1 = Friday
    assert add_work_days(at(9), 1, mon_to_fri) == at(12)  # Friday + 1 = Monday


@pytest.mark.parametrize(
    "due,days,before",
    [
        (at(5), 1, at(4)),  # Monday - 1 = Sunday
        (at(11), 1, at(8)),  # Sunday - 1 = Thursday
        (at(11), 0, at(11)),
    ],
)
def test_work_days_are_subtracted_skipping_days_off(due, days, before):
    assert subtract_work_days(due, days, SUN_TO_THU) == before


def test_an_organization_without_work_days_is_refused():
    with pytest.raises(ValueError):
        add_work_days(at(4), 1, [])


@pytest.mark.parametrize("value", [[], [7], [-1], ["1"], [True], "0,1", None])
def test_the_organization_refuses_work_days_that_cannot_be_counted(value):
    from django.core.exceptions import ValidationError

    from apps.accounts.models import validate_work_days

    with pytest.raises(ValidationError):
        validate_work_days(value)
    validate_work_days([6, 0, 1, 2, 3])
