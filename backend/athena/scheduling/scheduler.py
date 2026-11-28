"""The scheduler: an asyncio loop inside the API server that starts due schedules.

Rules (the same as cron's, plus Athena's one-run-at-a-time):
- It only runs while Athena runs. Fire times missed while Athena was closed are not caught up: on startup each
  schedule's next run is recomputed from now.
- A due schedule waits while another run is in flight and starts as soon as the slot is free; it never stacks
  (one pending start per schedule, whatever the number of fire times that passed).
- Each run is recorded in the schedule's history with its outcome (and the node that failed, or the gates that
  skipped the rest).
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime
from typing import Any

import structlog

from athena.core.dag import has_cycle
from athena.core.events import EventBroker
from athena.core.events import broker as default_broker
from athena.core.executor import execute, get_active_run_id
from athena.core.subflows import expand
from athena.storage import schedules as store
from athena.storage.files import load_pipeline

TICK_S = 15
log = structlog.get_logger()
_running: dict[str, str] = {}  # schedule name (lower) -> run id
_task: asyncio.Task[None] | None = None


class SlotBusy(RuntimeError):
    pass


def running_run(name: str) -> str | None:
    return _running.get(name.lower())


def catch_up(now: datetime | None = None) -> None:
    """At startup: schedules whose next run passed while Athena was closed move to their next future time."""
    t = now or store.now()
    for s in store.list_schedules():
        if s.enabled and (s.next_run is None or datetime.fromisoformat(s.next_run) <= t):
            store.update(s.name, next_run=store.next_run(s.cron, t))


async def start_run(name: str, trigger: str, event_broker: EventBroker | None = None) -> str:
    """Start a schedule's pipeline now. Returns the run id; the run continues in the background."""
    s = store.get(name)
    if get_active_run_id() is not None:
        raise SlotBusy("Another pipeline is running")
    try:
        spec, _ = expand(load_pipeline(s.pipeline), None)
    except FileNotFoundError as exc:
        raise store.ScheduleError(f"The pipeline file is gone: {s.pipeline}") from exc
    except ValueError as exc:
        raise store.ScheduleError(f"The pipeline file can't be loaded: {str(exc).splitlines()[0]}") from exc
    if has_cycle([{"id": n.id} for n in spec.nodes], [{"source": e.source, "target": e.target} for e in spec.edges]):
        raise store.ScheduleError("The pipeline has a cycle")
    run_id = str(uuid.uuid4())
    rec = store.RunRecord(run_id=run_id, trigger=trigger, started=store.now().isoformat())
    store.record(s.name, rec)
    b = event_broker or default_broker
    q = b.subscribe(run_id)
    _running[s.name.lower()] = run_id

    async def run() -> None:
        try:
            await execute(spec, run_id, b)
        except Exception as exc:  # noqa: BLE001 - the engine itself crashed: the run still gets an outcome
            rec.status, rec.error = "error", f"Execution engine crashed: {exc}"
            log.error("scheduled_run_crashed", schedule=s.name, run_id=run_id, error=str(exc))
        finally:
            _summarise(q, rec)
            b.unsubscribe(run_id, q)
            rec.finished = store.now().isoformat()
            _running.pop(s.name.lower(), None)
            with contextlib.suppress(store.ScheduleError):
                store.record(s.name, rec)
            log.info("scheduled_run_finished", schedule=s.name, run_id=run_id, status=rec.status)

    asyncio.get_running_loop().create_task(run())
    return run_id


def _summarise(q: asyncio.Queue[Any], rec: store.RunRecord) -> None:
    while not q.empty():
        e = q.get_nowait()
        kind = getattr(e, "type", None)
        if kind == "node_finish" and e.status == "error" and rec.error_node is None:
            rec.error_node, rec.error = e.node_id, (e.error.message if e.error else "failed")
        elif kind == "node_finish" and getattr(e, "halted", False):
            rec.skipped.append(e.node_id)
        elif kind == "run_finish" and rec.status == "running":
            rec.status = e.status


async def tick(now: datetime | None = None, event_broker: EventBroker | None = None) -> list[str]:
    """Start every due, enabled schedule the run slot allows. Returns the names started."""
    t = now or store.now()
    started = []
    for s in store.list_schedules():
        if not s.enabled or s.next_run is None or datetime.fromisoformat(s.next_run) > t or running_run(s.name):
            continue
        if get_active_run_id() is not None:
            break  # wait for the slot; due schedules start on a later tick
        store.update(s.name, next_run=store.next_run(s.cron, t))  # advance first: one start, however late
        try:
            await start_run(s.name, "schedule", event_broker)
            started.append(s.name)
        except (store.ScheduleError, SlotBusy) as exc:
            store.record(s.name, store.RunRecord(run_id=f"failed-{uuid.uuid4().hex[:8]}", trigger="schedule",
                                                 started=t.isoformat(), finished=t.isoformat(), status="error", error=str(exc)))
            log.warning("scheduled_run_not_started", schedule=s.name, error=str(exc))
    return started


async def _loop() -> None:
    while True:
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 - a broken schedules.json must not kill the loop
            log.error("scheduler_tick_failed", error=str(exc))
        await asyncio.sleep(TICK_S)


def start() -> None:
    global _task
    catch_up()
    _task = asyncio.get_running_loop().create_task(_loop())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
