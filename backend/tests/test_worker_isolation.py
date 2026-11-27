"""Runs execute in a worker process: misbehaving node code must not affect the API server."""
import os
from pathlib import Path

import pytest

import athena.core.executor as exe
from athena.config import settings
from athena.core.events import EventBroker
from athena.schemas.pipeline import PipelineSpec

IRIS_CSV = str(Path(__file__).parent / "fixtures" / "data" / "iris.csv")


def _custom_code_spec(code: str) -> PipelineSpec:
    return PipelineSpec(
        version=1, name="isolation",
        nodes=[
            {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": IRIS_CSV, "sep": ",", "header": True, "encoding": "utf-8"}},
            {"id": "n2", "type": "custom_code", "position": {"x": 200, "y": 0}, "config": {"code": code}},
        ],
        edges=[{"id": "e1", "source": "n1", "target": "n2", "source_port": 0, "target_port": 0}],
    )


async def _run(spec: PipelineSpec, run_id: str, *, cancel_after_start: bool = False) -> list:
    broker = EventBroker()
    q = broker.subscribe(run_id)
    if cancel_after_start:
        import asyncio

        async def cancel_when_n2_starts() -> None:
            while not any(getattr(e, "node_id", None) == "n2" and e.type == "node_start" for e in list(broker._buffers.get(run_id, []))):
                await asyncio.sleep(0.05)
            exe.cancel_run(run_id)

        task = asyncio.create_task(cancel_when_n2_starts())
        await exe.execute(spec, run_id, broker, prewarm_next=False)
        task.cancel()
    else:
        await exe.execute(spec, run_id, broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    return events


def _finish(events: list, node_id: str):
    return next(e for e in events if e.type == "node_finish" and e.node_id == node_id)


@pytest.mark.asyncio
async def test_user_code_runs_outside_the_api_process():
    events = await _run(_custom_code_spec("df['pid'] = os.getpid()\nreturn df".replace("os.getpid()", "__import__('os').getpid()")), "iso-pid")
    preview = _finish(events, "n2").preview
    pid_col = preview["columns"].index("pid")
    assert preview["rows"][0][pid_col] != os.getpid()


@pytest.mark.asyncio
async def test_handler_logs_reach_the_client():
    events = await _run(_custom_code_spec("return df"), "iso-logs")
    logs = [e for e in events if e.type == "node_log"]
    assert any(e.node_id == "n2" and "Custom code executed" in e.msg for e in logs)


@pytest.mark.asyncio
async def test_crashing_worker_is_reported_not_fatal():
    events = await _run(_custom_code_spec("__import__('os')._exit(3)"), "iso-crash")
    err = _finish(events, "n2")
    assert err.status == "error" and "exit code 3" in err.error.message
    assert events[-1].type == "run_finish" and events[-1].status == "error"
    assert exe.get_active_run_id() is None  # the slot is free for the next run


@pytest.mark.asyncio
async def test_hung_node_times_out(monkeypatch):
    monkeypatch.setattr(settings, "node_timeout_s", 2)
    events = await _run(_custom_code_spec("__import__('time').sleep(60)\nreturn df"), "iso-timeout")
    err = _finish(events, "n2")
    assert "Timed out after 2 s" in err.error.message
    assert events[-1].status == "error"


@pytest.mark.asyncio
async def test_stop_kills_a_node_that_ignores_cancellation(monkeypatch):
    monkeypatch.setattr(exe, "CANCEL_GRACE_S", 1.0)
    events = await _run(_custom_code_spec("__import__('time').sleep(60)\nreturn df"), "iso-cancel", cancel_after_start=True)
    assert _finish(events, "n2").status == "error"
    assert events[-1].type == "run_finish" and events[-1].status == "cancelled"


@pytest.mark.asyncio
async def test_custom_code_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ATHENA_ALLOW_CUSTOM_CODE", "false")  # read by the worker's settings
    exe.pool.shutdown()  # the standby was started with the old environment
    events = await _run(_custom_code_spec("return df"), "iso-disabled")
    assert "disabled" in _finish(events, "n2").error.message
