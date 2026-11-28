"""The cron parser and next-fire computation."""
# ruff: noqa: DTZ001  (cron works on naive local wall-clock times)
from datetime import datetime

import pytest

from athena.core.cron import CronError, describe, next_after, next_times, parse

T0 = datetime(2026, 11, 28, 10, 7, 30)  # a Saturday


def nxt(expr: str, after: datetime = T0) -> datetime:
    return next_after(parse(expr), after)


def test_common_schedules():
    assert nxt("*/15 * * * *") == datetime(2026, 11, 28, 10, 15)
    assert nxt("0 * * * *") == datetime(2026, 11, 28, 11, 0)
    assert nxt("30 2 * * *") == datetime(2026, 11, 29, 2, 30)
    assert nxt("@daily") == datetime(2026, 11, 29, 0, 0)
    assert nxt("0 9 * * mon-fri") == datetime(2026, 11, 30, 9, 0)  # Saturday -> Monday
    assert nxt("0 9 * * 7") == datetime(2026, 11, 29, 9, 0)  # 7 is Sunday too
    assert nxt("0 0 1 * *") == datetime(2026, 12, 1, 0, 0)
    assert nxt("@yearly") == datetime(2027, 1, 1, 0, 0)
    assert nxt("0 12 29 feb *") == datetime(2028, 2, 29, 12, 0)  # the next leap day


def test_strictly_after_and_lists_ranges_steps():
    assert nxt("7 10 * * *") == datetime(2026, 11, 29, 10, 7)  # 10:07 has passed (seconds in)
    assert nxt("8 10 * * *") == datetime(2026, 11, 28, 10, 8)
    assert nxt("5,50 * * * *") == datetime(2026, 11, 28, 10, 50)
    assert nxt("0 8-18/4 * * *") == datetime(2026, 11, 28, 12, 0)
    assert nxt("5/20 * * * *") == datetime(2026, 11, 28, 10, 25)
    assert next_times(parse("0 */6 * * *"), T0) == [datetime(2026, 11, 28, 12), datetime(2026, 11, 28, 18), datetime(2026, 11, 29, 0)]


def test_day_of_month_or_day_of_week_when_both_are_set():
    # cron: the 1st of the month OR any Monday
    assert nxt("0 0 1 * mon") == datetime(2026, 11, 30, 0, 0)
    assert nxt("0 0 1 * mon", datetime(2026, 11, 30, 1)) == datetime(2026, 12, 1, 0, 0)


@pytest.mark.parametrize("expr, msg", [
    ("* * * *", "5 fields"), ("61 * * * *", "out of range"), ("* * * * fun", "valid day of week"),
    ("*/0 * * * *", "positive"), ("5-1 * * * *", "backwards"), ("1,,2 * * * *", "Empty item"),
])
def test_bad_expressions_are_explained(expr, msg):
    with pytest.raises(CronError, match=msg):
        parse(expr)


def test_impossible_dates_never_fire():
    with pytest.raises(CronError, match="never fires"):
        nxt("0 0 30 feb *")


def test_descriptions():
    assert describe(parse("*/15 * * * *")) == "Every 15 minutes"
    assert describe(parse("@hourly")) == "Every hour"
    assert describe(parse("30 2 * * *")) == "Every day at 02:30"
    assert describe(parse("0 9 * * 1-5")) == "Weekdays at 09:00"
    assert describe(parse("0 6 1 * *")) == "Day 1 of every month at 06:00"
    assert describe(parse("7 3 */2 * *")) == "7 3 */2 * *"
