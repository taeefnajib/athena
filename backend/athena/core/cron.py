"""Cron expressions: parse the standard five fields and find the next fire times (pure, no dependencies).

``minute hour day-of-month month day-of-week``: ``*``, values, ranges ``a-b``, steps ``*/15`` or ``a-b/2``, lists
``1,15``, month and weekday names (``jan``, ``mon``), Sunday as 0 or 7, and the macros ``@hourly``, ``@daily``
(``@midnight``), ``@weekly``, ``@monthly``, ``@yearly`` (``@annually``). As in cron, when both day fields are
restricted a day matches either of them. Times are the machine's local time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

MACROS = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
          "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
DAYS = {d: i for i, d in enumerate(DAY_NAMES)}
FIELDS = (("minute", 0, 59, {}), ("hour", 0, 23, {}), ("day of month", 1, 31, {}), ("month", 1, 12, MONTHS),
          ("day of week", 0, 7, DAYS))


class CronError(ValueError):
    pass


@dataclass(frozen=True)
class Cron:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 = Sunday
    any_day: bool  # day of month is *
    any_weekday: bool  # day of week is *

    def matches_day(self, d: datetime) -> bool:
        dom, dow = d.day in self.days, (d.isoweekday() % 7) in self.weekdays
        if self.any_day or self.any_weekday:
            return dom and dow
        return dom or dow


def _value(token: str, lo: int, hi: int, names: dict[str, int], name: str) -> int:
    v = names.get(token.lower()) if names else None
    if v is None:
        if not token.isdigit():
            raise CronError(f"{token!r} isn't a valid {name}")
        v = int(token)
    if not lo <= v <= hi:
        raise CronError(f"{name.capitalize()} {v} is out of range ({lo}-{hi})")
    return v


def _field(text: str, lo: int, hi: int, names: dict[str, int], name: str) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"Empty item in the {name} field")
        rng, _, step_s = part.partition("/")
        step = 1
        if step_s:
            if not step_s.isdigit() or int(step_s) == 0:
                raise CronError(f"Step {step_s!r} in the {name} field must be a positive number")
            step = int(step_s)
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a_s, b_s = rng.split("-", 1)
            a, b = _value(a_s, lo, hi, names, name), _value(b_s, lo, hi, names, name)
            if a > b:
                raise CronError(f"Range {rng!r} in the {name} field goes backwards")
        else:
            a = _value(rng, lo, hi, names, name)
            b = hi if step_s else a  # "5/15" means from 5, every 15
        out.update(range(a, b + 1, step))
    return out


def parse(expr: str) -> Cron:
    text = MACROS.get(expr.strip().lower(), expr.strip())
    parts = text.split()
    if len(parts) != 5:
        raise CronError(f"A cron expression has 5 fields (minute hour day month weekday), got {len(parts)}: {expr!r}")
    sets = [_field(p, lo, hi, names, name) for p, (name, lo, hi, names) in zip(parts, FIELDS)]
    weekdays = {0 if d == 7 else d for d in sets[4]}
    return Cron(expr.strip(), frozenset(sets[0]), frozenset(sets[1]), frozenset(sets[2]), frozenset(sets[3]),
                frozenset(weekdays), parts[2] == "*", parts[4] == "*")


def next_after(cron: Cron, after: datetime, limit_years: int = 5) -> datetime:
    """The first fire time strictly after ``after`` (minute precision, same tzinfo as ``after``)."""
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = after + timedelta(days=366 * limit_years)
    while t <= end:
        if t.month not in cron.months:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        if not cron.matches_day(t):
            t = t.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if t.hour not in cron.hours:
            t = t.replace(minute=0) + timedelta(hours=1)
            continue
        if t.minute not in cron.minutes:
            t += timedelta(minutes=1)
            continue
        return t
    raise CronError(f"{cron.expr!r} never fires (e.g. February 30th)")


def next_times(cron: Cron, after: datetime, n: int = 3) -> list[datetime]:
    out, t = [], after
    for _ in range(n):
        t = next_after(cron, t)
        out.append(t)
    return out


def describe(cron: Cron) -> str:
    """A short English description for the common shapes; the expression itself otherwise."""
    every_day = cron.any_day and cron.any_weekday and len(cron.months) == 12
    mins, hours = sorted(cron.minutes), sorted(cron.hours)
    if every_day and len(hours) == 24:
        if len(mins) == 60:
            return "Every minute"
        if len(mins) > 1 and all(b - a == mins[1] - mins[0] for a, b in pairwise(mins)) and mins[0] == 0 and 60 % (mins[1] - mins[0]) == 0:
            return f"Every {mins[1] - mins[0]} minutes"
        if len(mins) == 1:
            return "Every hour" + (f" at :{mins[0]:02d}" if mins[0] else "")
    if len(mins) == 1 and len(hours) <= 4:
        at = ", ".join(f"{h:02d}:{mins[0]:02d}" for h in hours)
        if every_day:
            return f"Every day at {at}"
        names = [d.capitalize() for d in DAY_NAMES]
        if cron.any_day and len(cron.months) == 12:
            days = sorted(cron.weekdays)
            label = "Weekdays" if days == [1, 2, 3, 4, 5] else ", ".join(names[d] for d in days)
            return f"{label} at {at}"
        if cron.any_weekday and len(cron.months) == 12 and len(cron.days) == 1:
            return f"Day {min(cron.days)} of every month at {at}"
    return cron.expr
