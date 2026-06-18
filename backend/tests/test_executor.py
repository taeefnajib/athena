import asyncio
import pytest
from pathlib import Path
from athena.core.executor import execute, cancel_run, is_cancelled, _active_run_id, _cancelled_runs
from athena.core.events import EventBroker
from athena.schemas.pipeline import PipelineSpec


def _simple_spec(csv_path: str) -> PipelineSpec:
    return PipelineSpec(
        version=1, name="test",
        nodes=[
            {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": csv_path, "sep": ",", "header": True, "encoding": "utf-8"}},
            {"id": "n2", "type": "imputer", "position": {"x": 200, "y": 0}, "config": {"strategy": "mean", "fill_value": "0", "cols": ""}},
        ],
        edges=[
            {"id": "e1", "source": "n1", "target": "n2", "source_port": 0, "target_port": 0},
        ],
    )


IRIS_CSV = str(Path(__file__).parent / "fixtures" / "data" / "iris.csv")


@pytest.fixture(autouse=True)
def clean_executor_state():
    import athena.core.executor as exe
    exe._active_run_id = None
    exe._cancelled_runs.clear()
    yield
    exe._active_run_id = None
    exe._cancelled_runs.clear()


@pytest.mark.asyncio
async def test_happy_path_emits_events(tmp_path: Path):
    broker = EventBroker()
    spec = _simple_spec(IRIS_CSV)
    events = []

    q = broker.subscribe("run1")
    await execute(spec, "run1", broker)

    while not q.empty():
        events.append(await q.get())

    types = [e.type for e in events]
    assert "node_start" in types
    assert "node_finish" in types
    assert "run_finish" in types

    finishes = [e for e in events if e.type == "node_finish"]
    assert all(f.status == "success" for f in finishes)

    run_finish = next(e for e in events if e.type == "run_finish")
    assert run_finish.status == "completed"


@pytest.mark.asyncio
async def test_error_halts_downstream(tmp_path: Path):
    broker = EventBroker()
    spec = PipelineSpec(
        version=1, name="test",
        nodes=[
            {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": "/nonexistent.csv", "sep": ",", "header": True, "encoding": "utf-8"}},
            {"id": "n2", "type": "imputer", "position": {"x": 200, "y": 0}, "config": {"strategy": "mean", "fill_value": "0", "cols": ""}},
        ],
        edges=[{"id": "e1", "source": "n1", "target": "n2", "source_port": 0, "target_port": 0}],
    )
    q = broker.subscribe("run2")
    await execute(spec, "run2", broker)

    events = []
    while not q.empty():
        events.append(await q.get())

    error_finish = next((e for e in events if e.type == "node_finish" and e.status == "error"), None)
    assert error_finish is not None
    assert error_finish.node_id == "n1"

    n2_finish = next((e for e in events if e.type == "node_finish" and e.node_id == "n2"), None)
    assert n2_finish is None  # downstream was halted

    run_finish = next(e for e in events if e.type == "run_finish")
    assert run_finish.status == "error"


@pytest.mark.asyncio
async def test_unknown_node_type_errors(tmp_path: Path):
    broker = EventBroker()
    spec = PipelineSpec(
        version=1, name="test",
        nodes=[{"id": "n1", "type": "does_not_exist", "position": {"x": 0, "y": 0}, "config": {}}],
        edges=[],
    )
    q = broker.subscribe("run3")
    await execute(spec, "run3", broker)

    events = []
    while not q.empty():
        events.append(await q.get())

    node_finish = next(e for e in events if e.type == "node_finish")
    assert node_finish.status == "error"
    assert "Unknown" in node_finish.error.message


@pytest.mark.asyncio
async def test_cancellation(tmp_path: Path):
    import athena.core.executor as exe
    broker = EventBroker()
    spec = _simple_spec(IRIS_CSV)

    cancel_run("run4")  # cancel before start
    q = broker.subscribe("run4")
    await execute(spec, "run4", broker)

    events = []
    while not q.empty():
        events.append(await q.get())

    run_finish = next((e for e in events if e.type == "run_finish"), None)
    assert run_finish is not None
    assert run_finish.status == "cancelled"


@pytest.mark.asyncio
async def test_caching_skips_handler(tmp_path: Path):
    broker = EventBroker()
    spec = _simple_spec(IRIS_CSV)

    # First run - populate cache
    q1 = broker.subscribe("run5a")
    await execute(spec, "run5a", broker)
    events1 = []
    while not q1.empty():
        events1.append(await q1.get())
    assert any(e.type == "run_finish" and e.status == "completed" for e in events1)

    # Second run with same spec - should still complete (uses cache)
    broker2 = EventBroker()
    q2 = broker2.subscribe("run5b")
    await execute(spec, "run5b", broker2)
    events2 = []
    while not q2.empty():
        events2.append(await q2.get())
    assert any(e.type == "run_finish" and e.status == "completed" for e in events2)
