"""Execution runtimes: where a node runs (local worker, or a Ray task) must not change what it computes."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from athena.config import settings
from athena.connectors import store
from athena.main import app
from athena.runtime import adapters
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec

BACKEND = Path(__file__).parents[1]
client = TestClient(app)


def _n(nid, ntype, runtime=None, resources=None, **config):
    node = {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config, "runtime": runtime}
    if resources:
        node["resources"] = resources
    return node


def _e(eid, s, t, sp=0, tp=0):
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


def _spec(runtime=None, resources=None, path=None) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "rt", "nodes": [
        _n("csv", "csv_loader", path=path or str(BACKEND / "data.csv")), _n("imp", "imputer", runtime, strategy="median"),
        _n("tt", "train_test"), _n("rf", "rf", runtime, resources, n_estimators=30, n_jobs=2), _n("met", "metrics")],
        "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "rf", 0, 0), _e("d", "tt", "rf", 1, 1),
                  _e("e", "rf", "met", 0, 0), _e("f", "tt", "met", 2, 1), _e("g", "tt", "met", 3, 2)]})


def _run(spec: PipelineSpec, tmp: Path) -> tuple[str, list[dict], dict]:
    events: list[dict] = []
    artifacts: dict = {}
    run_id = str(uuid.uuid4())
    status = run_spec(spec, run_id, events.append, lambda: False, tmp / "cache" / run_id, artifacts_out=artifacts)
    return status, events, artifacts


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def test_parse_and_check(data_dir: Path, monkeypatch):
    assert adapters.parse(None) == ("python", "") and adapters.parse("ray:gpu-box") == ("ray", "gpu-box")
    with pytest.raises(adapters.RuntimeUnavailable, match="Unknown runtime"):
        adapters.parse("spark")
    with pytest.raises(adapters.RuntimeUnavailable, match="no connection"):
        adapters.parse("python:x")
    with pytest.raises(adapters.RuntimeUnavailable, match="No saved connection named 'nope'"):
        adapters.check("ray:nope")
    store.save_connection("db", "sql", {"url": "sqlite:///x.db"})
    with pytest.raises(adapters.RuntimeUnavailable, match="not a Ray cluster"):
        adapters.check("ray:db")
    monkeypatch.setattr(adapters, "ray_installed", lambda: False)
    with pytest.raises(adapters.RuntimeUnavailable, match="Ray isn't installed"):
        adapters.check("ray")


def test_an_unavailable_runtime_fails_the_node_cleanly(data_dir: Path):
    status, events, _ = _run(_spec(runtime="spark"), data_dir)
    assert status == "error"
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")
    assert err["node_id"] == "imp" and "Unknown runtime 'spark'" in err["error"]["message"]


def test_runtimes_api_lists_ray_connections(data_dir: Path):
    store.save_connection("cluster", "ray", {"address": "ray://head:10001"})
    values = [r["value"] for r in client.get("/api/runtimes").json()["runtimes"]]
    assert values == ["python", "ray", "ray:cluster"]


@pytest.fixture(scope="module")
def ray_cluster():
    ray = pytest.importorskip("ray")
    from athena.runtime import ray_runtime
    yield ray
    ray.shutdown()
    ray_runtime._CONNECTED = None


def test_ray_runtime_gives_the_same_results(data_dir: Path, ray_cluster):
    local_status, _, local = _run(_spec(), data_dir / "local")
    # a separate cache: the runtime isn't part of the cache key (same computation), so it would reuse the local results
    status, events, remote = _run(_spec(runtime="ray", resources={"cpu": 1}), data_dir / "ray")
    assert local_status == status == "completed"
    assert remote[("met", 0)] == local[("met", 0)]  # same metrics, wherever the model was trained
    logs = [e["msg"] for e in events if e["type"] == "node_log" and e["node_id"] == "rf"]
    assert any("Submitting to Ray (local cluster) with num_cpus=1" in m for m in logs)
    assert any("Running on Ray worker" in m for m in logs) and any("Fit complete" in m for m in logs)  # replayed from the task

    status, events, _ = _run(_spec(runtime="ray", path=str(data_dir / "missing.csv")), data_dir)  # fails before Ray: csv is local
    assert status == "error"

    bad = PipelineSpec.model_validate({"name": "bad", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("boom", "custom_code", "ray", code="raise ValueError('bad input on the cluster')")],
        "edges": [_e("a", "csv", "boom")]})
    status, events, _ = _run(bad, data_dir / "bad")
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]
    assert status == "error" and "bad input on the cluster" in err["message"]
    assert "remote.py" in err["traceback"] and "advanced.py" in err["traceback"]  # the traceback from the Ray worker

    from athena.config import settings as cfg
    cfg_before = cfg.allow_custom_code
    cfg.allow_custom_code = False
    try:  # checked before submitting: a remote cluster wouldn't know the setting
        status, events, _ = _run(bad, data_dir / "nocode")
        assert "Custom code is disabled" in next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]["message"]
    finally:
        cfg.allow_custom_code = cfg_before

    status, events, _ = _run(_spec(runtime="ray", resources={"gpu": 99}), data_dir / "gpu")
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]["message"]
    assert "asks for 99 GPU(s)" in err
