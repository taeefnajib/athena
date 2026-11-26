"""Run supervisor: lives in the API server, but never executes node code itself.

Each run is handed to a worker process (athena/runtime/worker.py). The supervisor relays the
worker's events to the broker and enforces what the worker can't be trusted to: per-node timeouts,
hard cancellation after a grace period, and reporting a crashed worker as a clean error.
"""
from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Any

import anyio
import structlog

from athena.config import settings
from athena.core.events import EventBroker, broker as default_broker
from athena.runtime.worker import worker_main
from athena.schemas.events import ErrorPayload, NodeFinish, NodeLog, NodeStart, RunFinish
from athena.schemas.pipeline import PipelineSpec

logger = structlog.get_logger()

CANCEL_GRACE_S = 3.0   # after Stop, how long the in-flight node gets before the worker is killed
POLL_S = 0.2

_active_run_id: str | None = None
_cancelled_runs: set[str] = set()


def get_active_run_id() -> str | None:
    return _active_run_id


def cancel_run(run_id: str) -> None:
    _cancelled_runs.add(run_id)


def is_cancelled(run_id: str) -> bool:
    return run_id in _cancelled_runs


def reset_active_run() -> None:
    """Clear leaked active-run state. Used by /api/runs/reset for recovery."""
    global _active_run_id
    _active_run_id = None
    _cancelled_runs.clear()


# ---- worker pool: one warm standby, a fresh process per run ------------------------------------

@dataclass
class _Worker:
    process: Any
    job_q: Any
    events: Any        # receive end of the worker's event pipe
    cancel_evt: Any


class WorkerPool:
    def __init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._standby: _Worker | None = None

    def _spawn(self) -> _Worker:
        job_q, cancel_evt = self._ctx.Queue(), self._ctx.Event()
        recv_end, send_end = self._ctx.Pipe(duplex=False)
        p = self._ctx.Process(target=worker_main, args=(job_q, send_end, cancel_evt), daemon=True, name="athena-worker")
        p.start()
        send_end.close()  # only the worker writes; the parent sees EOF when the worker exits
        return _Worker(p, job_q, recv_end, cancel_evt)

    def acquire(self) -> _Worker:
        w = self._standby if self._standby is not None and self._standby.process.is_alive() else None
        self._standby = None
        return w or self._spawn()

    def prewarm(self) -> None:
        """Start a standby worker so the next run doesn't wait for imports (~2 s)."""
        if self._standby is None or not self._standby.process.is_alive():
            self._standby = self._spawn()

    def shutdown(self) -> None:
        if self._standby is not None:
            _stop(self._standby)
            self._standby = None


def _pending(w: _Worker) -> bool:
    try:
        return bool(w.events.poll(0))
    except (EOFError, OSError):
        return False


def _stop(w: _Worker) -> None:
    if w.process.is_alive():
        w.process.kill()
    w.process.join(timeout=5)
    w.job_q.cancel_join_thread()
    w.job_q.close()
    w.events.close()


pool = WorkerPool()


# ---- events -----------------------------------------------------------------------------------

_EVENT_TYPES: dict[str, Any] = {
    "node_start": NodeStart, "node_log": NodeLog, "node_finish": NodeFinish, "run_finish": RunFinish,
}


def _to_event(msg: dict[str, Any]) -> Any:
    return _EVENT_TYPES[msg["type"]].model_validate(msg)


# ---- supervising one run ----------------------------------------------------------------------

async def execute(
    spec: PipelineSpec,
    run_id: str,
    event_broker: EventBroker | None = None,
    start_from: list[str] | None = None,
    prewarm_next: bool = True,
) -> None:
    global _active_run_id
    _active_run_id = run_id
    event_broker = event_broker or default_broker
    log = logger.bind(run_id=run_id)
    worker = pool.acquire()
    try:
        if is_cancelled(run_id):
            worker.cancel_evt.set()
        worker.job_q.put({
            "spec": spec.model_dump_json(), "run_id": run_id,
            "start_from": start_from, "data_dir": str(settings.data_dir),
        })
        await _supervise(worker, run_id, event_broker, log)
    finally:
        _stop(worker)
        _active_run_id = None
        _cancelled_runs.discard(run_id)
        if prewarm_next:
            pool.prewarm()


async def _supervise(w: _Worker, run_id: str, event_broker: EventBroker, log: Any) -> None:
    current: str | None = None          # node in flight
    node_started = 0.0
    cancel_asked: float | None = None

    async def publish(event: Any) -> None:
        await event_broker.publish(run_id, event)

    async def abort(node_message: str, run_status: str) -> None:
        if current is not None:
            await publish(NodeFinish(node_id=current, status="error",
                                     duration_ms=int((time.monotonic() - node_started) * 1000),
                                     error=ErrorPayload(message=node_message)))
        await publish(RunFinish(status=run_status))  # type: ignore[arg-type]

    while True:
        msg: dict[str, Any] | None = None
        try:
            if await anyio.to_thread.run_sync(w.events.poll, POLL_S):
                msg = w.events.recv()
        except (EOFError, OSError):  # the worker exited and the pipe is drained
            msg = None

        if msg is not None:
            kind = msg["type"]
            if kind == "_ready":
                continue
            if kind == "_crash":
                log.error("engine_crash", error=msg["message"], tb=msg["traceback"])
                await abort(f"Execution engine crashed: {msg['message']}", "error")
                return
            if kind == "_done":
                return  # run_finish was already relayed
            if kind == "node_start":
                current, node_started = msg["node_id"], time.monotonic()
            elif kind == "node_finish":
                current = None
            await publish(_to_event(msg))
            if kind == "run_finish":
                return
            continue

        # No event this tick: enforce cancellation, timeouts and crashes.
        now = time.monotonic()
        if is_cancelled(run_id) and cancel_asked is None:
            w.cancel_evt.set()
            cancel_asked = now
        if cancel_asked is not None and now - cancel_asked > CANCEL_GRACE_S:
            log.warning("cancel_kill", node_id=current)
            await abort("Cancelled: the node was stopped because it didn't finish after Stop.", "cancelled")
            return
        if current is not None and now - node_started > settings.node_timeout_s:
            log.warning("node_timeout", node_id=current, timeout_s=settings.node_timeout_s)
            await abort(f"Timed out after {settings.node_timeout_s} s (ATHENA_NODE_TIMEOUT_S).", "error")
            return
        if not w.process.is_alive() and not _pending(w):
            code = w.process.exitcode
            log.error("worker_died", exitcode=code)
            await abort(f"The worker process exited unexpectedly (exit code {code}).", "error")
            return
