"""Workflow spec v2: per-node execution policy (retry, cache, timeout, runtime) with v1 compatibility."""
from pathlib import Path

import pytest
from pydantic import ValidationError

import athena.core.executor as exe
from athena.core.events import EventBroker
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec
from athena.storage.files import load_pipeline, save_pipeline

IRIS_CSV = str(Path(__file__).parent / "fixtures" / "data" / "iris.csv")


def _spec(code: str, **node_extra) -> PipelineSpec:
    return PipelineSpec.model_validate({
        "version": 2, "name": "v2", "nodes": [
            {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": IRIS_CSV}},
            {"id": "n2", "type": "custom_code", "position": {"x": 1, "y": 0}, "config": {"code": code}, **node_extra},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    })


def _counting_code(counter: Path, fail_first: int = 0) -> str:
    """User code that counts its calls in a file and fails the first `fail_first` times."""
    p = str(counter).replace("\\", "/")
    return (
        f"from pathlib import Path\nc = Path('{p}')\nn = int(c.read_text()) + 1 if c.exists() else 1\nc.write_text(str(n))\n"
        f"if n <= {fail_first}:\n    raise RuntimeError(f'flaky failure {{n}}')\nreturn df"
    ).replace("from pathlib import Path\n", "Path = __import__('pathlib').Path\n")


def _run_inline(spec: PipelineSpec, cache_dir: Path) -> tuple[str, list[dict]]:
    events: list[dict] = []
    status = run_spec(spec, "inline", events.append, lambda: False, cache_dir)
    return status, events


def test_v1_files_load_as_v2_with_defaults():
    spec = PipelineSpec.model_validate({"version": 1, "nodes": [{"id": "a", "type": "csv_loader", "position": {"x": 0, "y": 0}}], "edges": []})
    assert spec.version == 2
    node = spec.nodes[0]
    assert node.cache is True and node.retry is None and node.timeout_s is None and node.runtime is None


def test_invalid_policy_is_rejected():
    with pytest.raises(ValidationError):
        _spec("return df", retry={"max_attempts": 0})
    with pytest.raises(ValidationError):
        _spec("return df", timeout_s=0)


def test_retry_recovers_from_a_flaky_node(tmp_path: Path):
    counter = tmp_path / "calls"
    status, events = _run_inline(_spec(_counting_code(counter, fail_first=2), retry={"max_attempts": 3, "backoff_s": 0}), tmp_path / "c")
    assert status == "completed" and counter.read_text() == "3"
    warnings = [e["msg"] for e in events if e["type"] == "node_log" and e["level"] == "warn"]
    assert any("Attempt 1 of 3 failed" in w for w in warnings)


def test_retry_gives_up_after_max_attempts(tmp_path: Path):
    counter = tmp_path / "calls"
    status, events = _run_inline(_spec(_counting_code(counter, fail_first=5), retry={"max_attempts": 2}), tmp_path / "c")
    assert status == "error" and counter.read_text() == "2"
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")
    assert "flaky failure 2" in err["error"]["message"]


# Custom code can read anything (files, services) the cache can't see, so it runs on every run whatever its
# cache setting; nodes downstream are still reused when its output is unchanged (tests/test_cache_reuse.py).
@pytest.mark.parametrize(("cache", "expected_calls"), [(True, "2"), (False, "2")])
def test_custom_code_always_reruns(tmp_path: Path, cache: bool, expected_calls: str):
    counter = tmp_path / "calls"
    spec = _spec(_counting_code(counter), cache=cache)
    for _ in range(2):
        assert _run_inline(spec, tmp_path / "shared-cache")[0] == "completed"
    assert counter.read_text() == expected_calls


def test_unknown_runtime_is_a_clear_node_error(tmp_path: Path):
    status, events = _run_inline(_spec("return df", runtime="ray"), tmp_path / "c")
    err = next(e for e in events if e["type"] == "node_finish" and e["node_id"] == "n2")
    assert status == "error" and "isn't available in local mode" in err["error"]["message"]


@pytest.mark.asyncio
async def test_per_node_timeout_overrides_the_global_one():
    broker = EventBroker()
    q = broker.subscribe("v2-timeout")
    await exe.execute(_spec("__import__('time').sleep(60)\nreturn df", timeout_s=1), "v2-timeout", broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    err = next(e for e in events if e.type == "node_finish" and e.node_id == "n2")
    assert "Timed out after 1 s" in err.error.message


def test_policy_survives_save_and_load(tmp_path: Path):
    spec = _spec("return df", retry={"max_attempts": 3, "backoff_s": 2}, cache=False, timeout_s=90,
                 resources={"memory_gb": 4})
    path = tmp_path / "p.athena"
    save_pipeline(str(path), spec)
    loaded = load_pipeline(str(path))
    n2 = loaded.node("n2")
    assert loaded.version == 2
    assert (n2.retry.max_attempts, n2.retry.backoff_s, n2.cache, n2.timeout_s, n2.resources.memory_gb) == (3, 2.0, False, 90, 4.0)
