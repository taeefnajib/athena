"""Schedules: run a saved pipeline file on a cron schedule. Kept in ``<data_dir>/schedules.json``.

A schedule points at a saved ``.athena`` file (not the canvas), so what runs is a version you saved and can
diff. Each keeps its next fire time and the history of its last runs.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from athena.config import settings
from athena.core.cron import CronError, next_after, parse

HISTORY = 50
_lock = threading.RLock()


class ScheduleError(ValueError):
    pass


class RunRecord(BaseModel):
    run_id: str
    trigger: str  # "schedule" | "manual"
    started: str
    finished: str | None = None
    status: str = "running"  # running | completed | error | cancelled
    error: str | None = None
    error_node: str | None = None
    skipped: list[str] = Field(default_factory=list)  # gates that skipped the rest (on_fail=skip)


class Schedule(BaseModel):
    name: str
    pipeline: str  # path to a saved .athena file
    cron: str
    enabled: bool = True
    next_run: str | None = None  # local time, ISO, minute precision
    history: list[RunRecord] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[\w .-]{1,60}", v):
            raise ValueError("Use 1-60 letters, digits, spaces, dots, dashes or underscores for the name")
        return v

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        try:
            parse(v)
        except CronError as exc:
            raise ValueError(str(exc)) from exc
        return v.strip()


def _path() -> Any:
    return settings.data_dir / "schedules.json"


def now() -> datetime:
    """Local wall-clock time, as cron uses."""
    return datetime.now().replace(microsecond=0)  # noqa: DTZ005 - cron schedules follow local wall-clock time


def _read() -> list[Schedule]:
    p = _path()
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Schedule.model_validate(s) for s in data.get("schedules", [])]


def _write(items: list[Schedule]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schedules": [s.model_dump() for s in items]}, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def list_schedules() -> list[Schedule]:
    with _lock:
        return _read()


def get(name: str) -> Schedule:
    for s in list_schedules():
        if s.name.lower() == name.strip().lower():
            return s
    raise ScheduleError(f"No schedule named {name!r}")


def next_run(cron: str, after: datetime | None = None) -> str:
    return next_after(parse(cron), after or now()).isoformat()


def upsert(name: str, pipeline: str, cron: str, enabled: bool = True) -> Schedule:
    """Create or update a schedule. Changing the cron or re-enabling recomputes the next run from now."""
    with _lock:
        items = _read()
        old = next((s for s in items if s.name.lower() == name.strip().lower()), None)
        new = Schedule(name=name, pipeline=pipeline, cron=cron, enabled=enabled, history=old.history if old else [])
        keep_next = old and old.cron == new.cron and old.enabled and new.enabled and old.next_run
        new.next_run = (old.next_run if keep_next else next_run(new.cron)) if new.enabled else None
        items = [s for s in items if s is not old] + [new]
        items.sort(key=lambda s: s.name.lower())
        _write(items)
        return new


def delete(name: str) -> None:
    with _lock:
        items = _read()
        left = [s for s in items if s.name.lower() != name.strip().lower()]
        if len(left) == len(items):
            raise ScheduleError(f"No schedule named {name!r}")
        _write(left)


def update(name: str, **changes: Any) -> Schedule:
    with _lock:
        items = _read()
        for i, s in enumerate(items):
            if s.name.lower() == name.strip().lower():
                items[i] = s.model_copy(update=changes)
                _write(items)
                return items[i]
        raise ScheduleError(f"No schedule named {name!r}")


def record(name: str, rec: RunRecord) -> None:
    """Add or replace (by run id) a run in the schedule's history, newest first."""
    with _lock:
        items = _read()
        for s in items:
            if s.name.lower() == name.strip().lower():
                s.history = [rec] + [h for h in s.history if h.run_id != rec.run_id]
                s.history = s.history[:HISTORY]
                _write(items)
                return
