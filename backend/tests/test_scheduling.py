"""Schedules: the store, the scheduler's rules, the API, drift-triggered retraining (Quality Gate on_fail=skip),
and the Airflow / Dagster exports."""
# ruff: noqa: DTZ001  (schedules use naive local wall-clock times, as cron does)
import asyncio
import io
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from athena.config import settings
from athena.core.events import EventBroker
from athena.main import app
from athena.scheduling import scheduler
from athena.storage import schedules as store
from tests.test_gates import _e, _n

client = TestClient(app)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def _csv(tmp: Path, name: str = "in.csv", shift: float = 0.0, n: int = 300, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"x": rng.normal(shift, 1, n), "y": rng.normal(0, 1, n)})
    df["target"] = (df["x"] + df["y"] > shift).astype(int)
    path = tmp / name
    df.to_csv(path, index=False)
    return path


def _pipeline_file(tmp: Path, nodes: list, edges: list, name: str = "job") -> Path:
    path = tmp / f"{name}.athena"
    path.write_text(json.dumps({"version": 2, "name": name, "nodes": nodes, "edges": edges}), encoding="utf-8")
    return path


def _copy_pipeline(tmp: Path) -> tuple[Path, Path]:
    out = tmp / "out.csv"
    return _pipeline_file(tmp, [_n("csv", "csv_loader", path=str(_csv(tmp))), _n("exp", "csv_export", path=str(out))],
                          [_e("a", "csv", "exp")]), out


async def _wait(name: str, timeout: float = 120) -> store.Schedule:
    for _ in range(int(timeout * 10)):
        if scheduler.running_run(name) is None:
            return store.get(name)
        await asyncio.sleep(0.1)
    raise AssertionError("the scheduled run didn't finish")


def test_store_validates_and_keeps_history(data_dir: Path):
    pipe, _ = _copy_pipeline(data_dir)
    s = store.upsert("Nightly retrain", str(pipe), "30 2 * * *")
    assert s.next_run and datetime.fromisoformat(s.next_run).strftime("%H:%M") == "02:30"
    assert store.upsert("nightly retrain", str(pipe), "30 2 * * *").next_run == s.next_run  # unchanged: kept
    assert store.upsert("Nightly retrain", str(pipe), "30 2 * * *", enabled=False).next_run is None
    with pytest.raises(ValueError, match="5 fields"):
        store.upsert("bad", str(pipe), "every day")
    with pytest.raises(ValueError, match="letters, digits"):
        store.upsert("a/b", str(pipe), "@daily")
    for i in range(store.HISTORY + 5):
        store.record("Nightly retrain", store.RunRecord(run_id=f"r{i}", trigger="schedule", started="t"))
    hist = store.get("NIGHTLY RETRAIN").history
    assert len(hist) == store.HISTORY and hist[0].run_id == f"r{store.HISTORY + 4}"
    store.delete("Nightly retrain")
    with pytest.raises(store.ScheduleError):
        store.get("Nightly retrain")


def test_catch_up_skips_missed_runs(data_dir: Path):
    pipe, out = _copy_pipeline(data_dir)
    store.upsert("s", str(pipe), "0 * * * *")
    store.update("s", next_run="2020-01-01T00:00:00")  # missed while Athena was closed
    t = datetime(2026, 11, 28, 10, 7)
    scheduler.catch_up(t)
    assert store.get("s").next_run == "2026-11-28T11:00:00" and not out.exists() and store.get("s").history == []


@pytest.mark.asyncio
async def test_a_due_schedule_runs_once_and_is_recorded(data_dir: Path):
    pipe, out = _copy_pipeline(data_dir)
    store.upsert("copy", str(pipe), "*/5 * * * *")
    store.update("copy", next_run="2026-11-28T09:00:00")  # many fire times have passed: still one run
    now = datetime(2026, 11, 28, 10, 7)
    assert await scheduler.tick(now, EventBroker()) == ["copy"]
    assert await scheduler.tick(now, EventBroker()) == []  # already running / advanced
    s = await _wait("copy")
    assert s.next_run == "2026-11-28T10:10:00"
    rec = s.history[0]
    assert (rec.trigger, rec.status, rec.error) == ("schedule", "completed", None) and rec.finished
    assert len(s.history) == 1 and out.exists()


@pytest.mark.asyncio
async def test_due_schedules_wait_for_the_run_slot(data_dir: Path, monkeypatch):
    pipe, _ = _copy_pipeline(data_dir)
    store.upsert("copy", str(pipe), "@hourly")
    store.update("copy", next_run="2026-11-28T09:00:00")
    monkeypatch.setattr(scheduler, "get_active_run_id", lambda: "someone-else")
    assert await scheduler.tick(datetime(2026, 11, 28, 10, 7), EventBroker()) == []
    assert store.get("copy").next_run == "2026-11-28T09:00:00" and store.get("copy").history == []  # still due
    monkeypatch.setattr(scheduler, "get_active_run_id", lambda: None)
    assert await scheduler.tick(datetime(2026, 11, 28, 10, 8), EventBroker()) == ["copy"]
    await _wait("copy")


@pytest.mark.asyncio
async def test_failures_are_recorded(data_dir: Path):
    pipe = _pipeline_file(data_dir, [_n("csv", "csv_loader", path=str(data_dir / "missing.csv"))], [], "broken")
    store.upsert("broken", str(pipe), "@hourly")
    await scheduler.start_run("broken", "manual", EventBroker())
    rec = (await _wait("broken")).history[0]
    assert rec.status == "error" and rec.error_node == "csv" and "missing.csv" in rec.error

    pipe.unlink()  # the file went away after the schedule was made
    store.update("broken", next_run="2026-11-28T09:00:00")
    assert await scheduler.tick(datetime(2026, 11, 28, 10, 7), EventBroker()) == []
    rec = store.get("broken").history[0]
    assert rec.status == "error" and "file is gone" in rec.error


def test_api(data_dir: Path):
    pipe, _ = _copy_pipeline(data_dir)
    p = client.get("/api/schedules/preview", params={"cron": "0 9 * * 1-5"}).json()
    assert p["description"] == "Weekdays at 09:00" and len(p["next"]) == 3
    assert client.get("/api/schedules/preview", params={"cron": "0 25 * * *"}).json()["detail"]["code"] == "CRON_INVALID"
    bad = client.put("/api/schedules", json={"name": "x", "pipeline": str(data_dir / "nope.athena"), "cron": "@daily"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "FILE_NOT_FOUND"
    bad = client.put("/api/schedules", json={"name": "x", "pipeline": str(pipe), "cron": "sometimes"})
    assert bad.json()["detail"]["code"] == "SCHEDULE_INVALID" and "5 fields" in bad.json()["detail"]["detail"]
    made = client.put("/api/schedules", json={"name": "Nightly", "pipeline": str(pipe), "cron": "@daily"}).json()
    assert made["description"] == "Every day at 00:00" and made["running_run"] is None
    listed = client.get("/api/schedules").json()
    assert [s["name"] for s in listed["schedules"]] == ["Nightly"] and listed["scheduler_enabled"] is True
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/schedules/Nightly/export", params={"target": "dagster"}).content))
    assert sorted(z.namelist()) == ["job/README.md", "job/job_dagster.py", "job/job_pipeline.py", "job/job_steps.py"]
    assert "cron_schedule='@daily'" in z.read("job/job_dagster.py").decode()
    assert client.post("/api/schedules/nope/run").status_code == 404
    assert client.delete("/api/schedules/Nightly").json() == {"ok": True}
    assert client.delete("/api/schedules/Nightly").status_code == 404


def _retrain_spec(tmp: Path, live: Path, model_path: Path) -> list:
    """Retrain only when the new data drifted from the training data."""
    nodes = [_n("ref", "csv_loader", path=str(_csv(tmp, "ref.csv"))), _n("live", "csv_loader", path=str(live)),
             _n("drift", "evidently_drift", columns="x, y"),
             _n("gate", "quality_gate", rules="dataset_drift == 1", on_fail="skip"),
             _n("tt", "train_test"), _n("lr", "log_reg"), _n("save", "model_saver", path=str(model_path))]
    edges = [_e("a", "live", "drift", 0, 0), _e("b", "ref", "drift", 0, 1), _e("c", "drift", "gate", 0, 0),
             _e("d", "live", "gate", 0, 4), _e("f", "gate", "tt", 2, 0), _e("g", "tt", "lr", 0, 0), _e("h", "tt", "lr", 1, 1),
             _e("i", "lr", "save", 0, 0)]
    return [nodes, edges]


@pytest.mark.asyncio
async def test_retraining_triggered_by_drift(data_dir: Path):
    pytest.importorskip("evidently")
    model = data_dir / "model.joblib"
    stable = _pipeline_file(data_dir, *_retrain_spec(data_dir, _csv(data_dir, "same.csv", seed=1), model), "stable")
    store.upsert("stable", str(stable), "@daily")
    await scheduler.start_run("stable", "manual", EventBroker())
    rec = (await _wait("stable")).history[0]
    assert rec.status == "completed" and rec.skipped == ["gate"] and not model.exists()  # no drift: no retraining

    drifted = _pipeline_file(data_dir, *_retrain_spec(data_dir, _csv(data_dir, "new.csv", shift=1.5, seed=2), model), "drifted")
    store.upsert("drifted", str(drifted), "@daily")
    await scheduler.start_run("drifted", "manual", EventBroker())
    rec = (await _wait("drifted")).history[0]
    assert rec.status == "completed" and rec.skipped == [] and model.exists()  # drift: retrained on the new data


STUBS = {
    # Just enough of Airflow and Dagster to load the generated files and run their tasks in dependency order.
    "airflow/__init__.py": """
REGISTRY = []
class DAG:
    def __init__(self, **kw): self.kw = kw; self.tasks = {}; self.deps = []; REGISTRY.append(self)
    def __enter__(self): return self
    def __exit__(self, *a): return False
""",
    "airflow/exceptions.py": "class AirflowSkipException(Exception): pass\n",
    "airflow/operators/__init__.py": "",
    "airflow/operators/python.py": """
import airflow
class PythonOperator:
    def __init__(self, task_id, python_callable, op_kwargs):
        self.task_id, self.fn, self.kwargs, self.dag = task_id, python_callable, op_kwargs, airflow.REGISTRY[-1]
        self.dag.tasks[task_id] = self
    def __rshift__(self, other): self.dag.deps.append((self.task_id, other.task_id)); return other
""",
    "dagster.py": """
class DefaultScheduleStatus: RUNNING = "running"
class Nothing: pass
class In:
    def __init__(self, t): pass
class Out:
    def __init__(self, t, is_required=True): pass
class Output:
    def __init__(self, value): self.value = value
CALLS = []
class _Op:
    def __init__(self, fn, name, ins): self.fn, self.name, self.ins = fn, name, ins
    def __call__(self, **after): CALLS.append((self, list(after.values()))); return self.name
def op(name, ins, out): return lambda fn: _Op(fn, name, ins)
def job(name, description):
    def wrap(fn): fn(); return fn
    return wrap
class ScheduleDefinition:
    def __init__(self, job, cron_schedule, default_status): self.cron = cron_schedule
class Definitions:
    def __init__(self, jobs, schedules): self.schedules = schedules
""",
}

RUNNER = """
import importlib.util, sys, types
spec = importlib.util.spec_from_file_location("orch", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
state = {}
if sys.argv[2] == "airflow":
    import airflow
    from airflow.exceptions import AirflowSkipException
    dag = airflow.REGISTRY[-1]
    print("SCHEDULE", dag.kw["schedule"], dag.kw["catchup"], dag.kw["max_active_runs"])
    for tid, task in dag.tasks.items():  # NODES is in run order
        ups = [a for a, b in dag.deps if b == tid]
        if any(state[u] != "success" for u in ups):
            state[tid] = "upstream_" + ("failed" if any(state[u].endswith("failed") for u in ups) else "skipped")
            continue
        try:
            task.fn(**task.kwargs, run_id="run1"); state[tid] = "success"
        except AirflowSkipException:
            state[tid] = "skipped"
        except RuntimeError as exc:
            state[tid] = "failed"; print("FAILED", tid, exc)
else:
    import dagster
    print("SCHEDULE", mod.defs.schedules[0].cron)
    produced = set()
    for op, after in dagster.CALLS:
        if any(a not in produced for a in after):
            state[op.name] = "skipped"; continue
        try:
            ctx = types.SimpleNamespace(run_id="run1", log=types.SimpleNamespace(info=print))
            if any(isinstance(o, dagster.Output) for o in op.fn(ctx)):
                produced.add(op.name); state[op.name] = "success"
            else:
                state[op.name] = "skipped"
        except RuntimeError as exc:
            state[op.name] = "failed"; print("FAILED", op.name, exc)
print("STATES", " ".join(f"{k}={v}" for k, v in state.items()))
"""


@pytest.mark.parametrize("target", ["airflow", "dagster"])
def test_orchestrator_exports_run_the_pipeline(tmp_path: Path, target: str):
    stubs = tmp_path / "stubs"
    for rel, src in STUBS.items():
        (stubs / rel).parent.mkdir(parents=True, exist_ok=True)
        (stubs / rel).write_text(src, encoding="utf-8")
    (tmp_path / "runner.py").write_text(RUNNER, encoding="utf-8")
    csv = _csv(tmp_path)

    def run(rules: str, on_fail: str, out_name: str) -> tuple[str, Path]:
        out = tmp_path / out_name
        nodes = [_n("csv", "csv_loader", path=str(csv)), _n("m", "drift_detect"),
                 _n("gate", "quality_gate", rules=rules, on_fail=on_fail), _n("exp", "csv_export", path=str(out))]
        spec = {"version": 2, "name": f"Churn {out_name}", "nodes": nodes, "edges": [
            _e("a", "csv", "m", 0, 0), _e("a2", "csv", "m", 0, 1), _e("b", "m", "gate", 0, 0), _e("c", "csv", "gate", 0, 4), _e("d", "gate", "exp", 2, 0)]}
        res = client.post("/api/pipelines/export", json={"spec": spec, "format": target, "cron": "15 3 * * *"})
        assert res.status_code == 200, res.text
        folder = tmp_path / out_name.replace(".", "_")
        zipfile.ZipFile(io.BytesIO(res.content)).extractall(folder)
        orch = next(folder.rglob(f"*_{target}.py"))
        proc = subprocess.run([sys.executable, str(tmp_path / "runner.py"), str(orch), target], capture_output=True, text=True, check=False,
                              env={**__import__("os").environ, "PYTHONPATH": str(stubs)}, cwd=tmp_path, timeout=300)
        assert proc.returncode == 0, proc.stderr[-2000:]
        return proc.stdout, out

    stdout, out = run("columns_checked >= 2", "stop", "pass.csv")
    assert "SCHEDULE 15 3 * * *" in stdout and out.exists()
    assert "STATES step_csv=success step_m=success step_gate=success step_exp=success" in stdout  # one task per node
    if target == "airflow":
        assert "False 1" in stdout  # catchup off, never overlapping
    stdout, out = run("columns_checked > 100", "skip", "skip.csv")
    assert "step_gate=skipped step_exp=" in stdout and "FAILED" not in stdout and not out.exists()  # skipped, not failed
    stdout, out = run("columns_checked > 100", "stop", "stop.csv")
    assert "step_gate=failed" in stdout and "Quality gate failed" in stdout and not out.exists()


def test_steps_module_matches_the_script(tmp_path: Path, monkeypatch):
    """The per-node steps, run in order through their artifact files, compute what the single script computes."""
    import pickle

    from athena.core.codegen import pipeline_to_python
    from athena.core.orchestrator_steps import pipeline_to_steps
    from athena.schemas.pipeline import PipelineSpec
    backend = Path(__file__).parents[1]
    spec = PipelineSpec.model_validate({"version": 2, "name": "steps", "nodes": [
        _n("csv", "csv_loader", path=str(backend / "data.csv")), _n("imp", "imputer", strategy="median"), _n("tt", "train_test"),
        _n("rf", "rf", n_estimators=10), _n("met", "metrics")], "edges": [
        _e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "rf", 0, 0), _e("d", "tt", "rf", 1, 1),
        _e("e", "rf", "met", 0, 0), _e("f", "tt", "met", 2, 1), _e("g", "tt", "met", 3, 2)]})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATHENA_ARTIFACTS", str(tmp_path / "artifacts"))
    script: dict = {"__name__": "__main__"}
    exec(compile(pipeline_to_python(spec), "pipeline.py", "exec"), script)  # noqa: S102 - the export under test
    steps_src = pipeline_to_steps(spec, "steps")
    (tmp_path / "steps_mod.py").write_text(steps_src, encoding="utf-8")
    proc = subprocess.run([sys.executable, "steps_mod.py"], cwd=tmp_path, capture_output=True, text=True, timeout=300,
                          env={**__import__("os").environ, "ATHENA_ARTIFACTS": str(tmp_path / "artifacts")}, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    run_dir = next((tmp_path / "artifacts" / "steps").iterdir())
    with (run_dir / "report_met.pkl").open("rb") as fh:
        assert pickle.load(fh) == script["report_met"]
    assert {p.stem for p in run_dir.iterdir()} >= {"df_csv", "df_imp", "X_train_tt", "model_rf", "report_met"}


def test_next_run_is_in_the_future(data_dir: Path):
    pipe, _ = _copy_pipeline(data_dir)
    s = store.upsert("soon", str(pipe), "* * * * *")
    assert timedelta(0) < datetime.fromisoformat(s.next_run) - store.now() <= timedelta(minutes=1)
