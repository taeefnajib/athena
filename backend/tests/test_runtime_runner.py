"""Remote runners: a real `athena-runner` process on a local port, driven by Athena's runner runtime and its API."""
import json
import pickle
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from athena.config import settings
from athena.connectors import store
from athena.runner.__main__ import main as runner_main
from athena.runtime import runner_runtime
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec

BACKEND = Path(__file__).parents[1]
TOKEN = "test-token-" + uuid.uuid4().hex


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    work = tmp_path_factory.mktemp("runner-work")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "athena.runner", "--port", str(port), "--token", TOKEN, "--work-dir", str(work),
                             "--max-jobs", "1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}"
    client = runner_runtime.RunnerClient(url, TOKEN)
    for _ in range(150):
        try:
            client.json("GET", "/info")
            break
        except runner_runtime.RunnerError:
            if proc.poll() is not None:
                raise AssertionError(proc.stdout.read()) from None
            time.sleep(0.2)
    yield url, client, work
    proc.kill()
    proc.wait(10)


@pytest.fixture
def connected(runner, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(runner_runtime, "POLL_S", 0.2)
    from athena.connectors import secrets
    old = secrets.get_store()
    secrets.set_store(secrets.MemoryStore())  # never the real keychain
    url, _, _ = runner
    store.save_connection("box", "runner", {"url": url, "token": TOKEN})
    yield runner
    secrets.set_store(old)


def _n(nid, ntype, runtime=None, **config):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config, "runtime": runtime}


def _e(eid, s, t, sp=0, tp=0):
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


def _spec(runtime=None) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "runner", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("imp", "imputer", runtime, strategy="median"),
        _n("tt", "train_test"), _n("rf", "rf", runtime, n_estimators=25), _n("met", "metrics")],
        "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "rf", 0, 0), _e("d", "tt", "rf", 1, 1),
                  _e("e", "rf", "met", 0, 0), _e("f", "tt", "met", 2, 1), _e("g", "tt", "met", 3, 2)]})


def _run(spec: PipelineSpec, cache: Path, cancelled=lambda: False, emit=None):
    events: list[dict] = []
    artifacts: dict = {}

    def sink(e: dict) -> None:
        events.append(e)
        if emit:
            emit(e)

    status = run_spec(spec, str(uuid.uuid4()), sink, cancelled, cache / "c", artifacts_out=artifacts)
    return status, events, artifacts


def _job_dirs(work: Path) -> list[Path]:
    return [p for p in work.iterdir() if p.is_dir()]


def test_runner_gives_the_same_results(connected, tmp_path: Path):
    _, _, work = connected
    local_status, _, local = _run(_spec(), tmp_path / "local")
    status, events, remote = _run(_spec("runner:box"), tmp_path / "remote")
    assert local_status == status == "completed", [e for e in events if e.get("status") == "error"]
    assert remote[("met", 0)] == local[("met", 0)]
    logs = [e["msg"] for e in events if e["type"] == "node_log" and e["node_id"] == "rf"]
    assert logs[0].startswith("Sent to runner http://127.0.0.1:") and any("Running on runner" in m for m in logs)
    assert sum("Fit complete" in m for m in logs) == 1  # streamed once, not replayed again at the end
    assert _job_dirs(work) == []  # finished jobs are deleted from the runner


def test_logs_stream_while_the_node_runs_and_jobs_queue(connected):
    _, client, _ = connected
    payload = {"node_type": "custom_code", "config": {"code": "import time; time.sleep(3); return df"}, "inputs": [__import__("pandas").DataFrame({"a": [1]})],
               "run_id": "r", "node_id": "slow"}
    first = client.json("POST", "/jobs", pickle.dumps(payload), {"Content-Type": "application/octet-stream"})
    second = client.json("POST", "/jobs", pickle.dumps(payload), {"Content-Type": "application/octet-stream"})
    assert second["state"] == "queued"  # one slot (--max-jobs 1)
    for _ in range(100):
        st = client.json("GET", f"/jobs/{first['job_id']}")
        if st["state"] == "running" and st["lines"]:
            break
        time.sleep(0.1)
    assert st["state"] == "running" and "Running on runner" in st["lines"][0][1]  # a line before the node finished
    assert client.json("GET", f"/jobs/{first['job_id']}?since=1")["lines"] == []
    for job in (first, second):
        client.request("DELETE", f"/jobs/{job['job_id']}")


def test_failures(connected, tmp_path: Path):
    _, client, _ = connected
    bad = PipelineSpec.model_validate({"name": "bad", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("boom", "custom_code", "runner:box", code="raise ValueError('bad rows on the box')")],
        "edges": [_e("a", "csv", "boom")]})
    status, events, _ = _run(bad, tmp_path / "a")
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]
    assert status == "error" and "bad rows on the box" in err["message"] and "advanced.py" in err["traceback"]

    job = client.json("POST", "/jobs", b"not a pickle", {"Content-Type": "application/octet-stream"})  # the job process itself fails
    for _ in range(100):
        st = client.json("GET", f"/jobs/{job['job_id']}")
        if st["state"] == "failed":
            break
        time.sleep(0.1)
    assert st["state"] == "failed" and "exited with code" in st["error"]
    client.request("DELETE", f"/jobs/{job['job_id']}")


def test_stop_kills_the_job(connected, tmp_path: Path):
    _, _, work = connected
    spec = PipelineSpec.model_validate({"name": "slow", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("wait", "custom_code", "runner:box", code="import time; time.sleep(60); return df")],
        "edges": [_e("a", "csv", "wait")]})
    stop = {"now": False}

    def emit(e: dict) -> None:
        if e["type"] == "node_log" and "Running on runner" in e["msg"]:
            stop["now"] = True

    status, _, _ = _run(spec, tmp_path / "s", cancelled=lambda: stop["now"], emit=emit)
    assert status in ("cancelled", "error")
    assert _job_dirs(work) == []  # deleted, process killed


def test_token_is_required(connected):
    url, _, _ = connected
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(urllib.request.Request(f"{url}/info", headers=headers), timeout=10)
        assert exc.value.code == 401
    from athena.connectors.runner import RunnerConfig, RunnerConnector
    res = RunnerConnector().test(RunnerConfig(url=url, token="wrong"))
    assert not res.ok and "401" in res.message
    ok = RunnerConnector().test(RunnerConfig(url=url, token=TOKEN))
    assert ok.ok and "job slot" in ok.message and json.dumps(ok.details)


def test_cli_refuses_the_network_without_a_token(monkeypatch, capsys):
    monkeypatch.delenv("ATHENA_RUNNER_TOKEN", raising=False)
    assert runner_main(["--host", "0.0.0.0", "--token", ""]) == 2
    assert "needs a token" in capsys.readouterr().err


def test_runtime_validation(connected):
    from athena.runtime import adapters
    with pytest.raises(adapters.RuntimeUnavailable, match="needs a Athena runner connection|needs an? Athena runner connection"):
        adapters.parse("runner")
    from fastapi.testclient import TestClient

    from athena.main import app
    assert "runner:box" in [r["value"] for r in TestClient(app).get("/api/runtimes").json()["runtimes"]]
