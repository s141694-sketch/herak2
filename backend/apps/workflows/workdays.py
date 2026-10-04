"""Counting in the organization's work days (spec 6.3, D58).

Work days are Python weekday numbers (Monday=0) from Organization.work_days, read in the platform's time
zone. There are no public holidays in the first version.
"""

from datetime import datetime, time, timedelta

from django.utils import timezone


def _check(work_days) -> set[int]:
    days = set(work_days)
    if not days:
        raise ValueError("an organization needs at least one work day")
    return days


def add_work_days(start: datetime, days: int, work_days) -> datetime:
    """``days`` work days after ``start``, at the same time of day. A start on a day off counts from the start
    of the next work day."""
    week = _check(work_days)
    moment = timezone.localtime(start)
    if moment.weekday() not in week:
        day = moment.date() + timedelta(days=1)
        while day.weekday() not in week:
            day += timedelta(days=1)
        moment = timezone.make_aware(datetime.combine(day, time()), moment.tzinfo)
    return _step(moment, days, week, +1)


def subtract_work_days(moment: datetime, days: int, work_days) -> datetime:
    """``days`` work days before ``moment``, at the same time of day."""
    return _step(timezone.localtime(moment), days, _check(work_days), -1)


def _step(moment: datetime, days: int, week: set[int], direction: int) -> datetime:
    day = moment.date()
    for _ in range(days):
        day += timedelta(days=direction)
        while day.weekday() not in week:
            day += timedelta(days=direction)
    # Rebuilt from the wall-clock time, so a change of UTC offset between the two days keeps the local hour.
    return timezone.make_aware(datetime.combine(day, moment.timetz().replace(tzinfo=None)), moment.tzinfo)
