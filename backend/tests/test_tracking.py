"""MLflow tracking and the model registry nodes, against Athena's local store (needs the mlflow extra)."""
import shutil
from pathlib import Path

import pytest

mlflow = pytest.importorskip("mlflow")

import athena.core.executor as exe  # noqa: E402
from athena.config import settings  # noqa: E402
from athena.core.codegen import pipeline_to_python  # noqa: E402
from athena.core.events import EventBroker  # noqa: E402
from athena.schemas.pipeline import PipelineSpec  # noqa: E402
from athena.tracking.session import local_db, local_uri  # noqa: E402

DATA_CSV = str(Path(__file__).parents[1] / "data.csv")


@pytest.fixture(scope="session")
def template_store(tmp_path_factory) -> Path:
    """Creating an MLflow SQLite store runs its migrations (~20 s): do it once, copy it per test."""
    from athena.tracking.session import ensure_experiment, mlflow_session
    root = tmp_path_factory.mktemp("mlflow-template")
    old = settings.data_dir
    settings.data_dir = root
    try:
        with mlflow_session("") as dest:
            ensure_experiment(dest, "athena")
    finally:
        settings.data_dir = old
    return root / "mlflow" / "mlflow.db"


@pytest.fixture(autouse=True)
def local_store(template_store: Path) -> None:
    local_db().parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template_store, local_db())


def _client():
    return mlflow.MlflowClient(tracking_uri=local_uri(), registry_uri=local_uri())


def _pipeline(name: str, tracking: dict | None, extra_nodes: list | None = None, extra_edges: list | None = None) -> PipelineSpec:
    nodes = [
        {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": DATA_CSV}},
        {"id": "n2", "type": "imputer", "position": {"x": 1, "y": 0}, "config": {}},
        {"id": "n3", "type": "train_test", "position": {"x": 2, "y": 0}, "config": {}},
        {"id": "n4", "type": "rf", "position": {"x": 3, "y": 0}, "config": {"n_estimators": 20}},
        {"id": "n5", "type": "metrics", "position": {"x": 4, "y": 0}, "config": {}},
    ] + (extra_nodes or [])
    edges = [
        {"id": "e1", "source": "n1", "target": "n2"}, {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "target": "n4", "source_port": 0, "target_port": 0},
        {"id": "e4", "source": "n3", "target": "n4", "source_port": 1, "target_port": 1},
        {"id": "e5", "source": "n4", "target": "n5", "source_port": 0, "target_port": 0},
        {"id": "e6", "source": "n3", "target": "n5", "source_port": 2, "target_port": 1},
        {"id": "e7", "source": "n3", "target": "n5", "source_port": 3, "target_port": 2},
    ] + (extra_edges or [])
    return PipelineSpec.model_validate({"name": name, "nodes": nodes, "edges": edges,
                                        "metadata": {"tracking": tracking} if tracking else {}})


async def _run(spec: PipelineSpec, run_id: str) -> list:
    broker = EventBroker()
    q = broker.subscribe(run_id)
    await exe.execute(spec, run_id, broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    return events


def _tracking_event(events: list) -> dict:
    return next(e.tracking for e in events if e.type == "run_info" and e.tracking)


@pytest.mark.asyncio
async def test_tracked_run_logs_params_metrics_code_and_model():
    events = await _run(_pipeline("churn", {"enabled": True}), "trk-1")
    assert events[-1].status == "completed"
    info = _tracking_event(events)
    assert info["experiment"] == "churn" and info["backend"] == "mlflow"

    run = _client().get_run(info["run_id"])
    assert run.info.status == "FINISHED"
    assert run.data.params["n4.n_estimators"] == "20"
    assert 0.5 < run.data.metrics["n5.accuracy"] <= 1.0
    assert run.data.tags["athena.run_id"] == "trk-1"
    artifacts = {a.path for a in _client().list_artifacts(info["run_id"], "athena")}
    assert artifacts == {"athena/pipeline.json", "athena/pipeline.py"}
    logged = _client().search_logged_models(experiment_ids=[info["experiment_id"]])
    assert [m.name for m in logged] == ["n4"]


@pytest.mark.asyncio
async def test_untracked_pipeline_logs_nothing():
    events = await _run(_pipeline("plain", None), "trk-2")
    assert not any(e.type == "run_info" for e in events)
    assert _client().get_experiment_by_name("plain") is None


@pytest.mark.asyncio
async def test_failed_run_is_marked_failed():
    spec = _pipeline("broken", {"enabled": True})
    spec.nodes[0].config["path"] = "/does/not/exist.csv"
    events = await _run(spec, "trk-3")
    assert events[-1].status == "error"
    assert _client().get_run(_tracking_event(events)["run_id"]).info.status == "FAILED"


@pytest.mark.asyncio
async def test_tracking_problems_never_fail_the_run():
    events = await _run(_pipeline("bad-dest", {"enabled": True, "connection": "no-such-connection"}), "trk-4")
    assert events[-1].status == "completed"
    warnings = [e.warning for e in events if e.type == "run_info" and e.warning]
    assert any("no-such-connection" in w for w in warnings)


@pytest.mark.asyncio
async def test_register_in_a_tracked_run_reuses_the_logged_model():
    register = [{"id": "r1", "type": "mlflow_register", "position": {"x": 5, "y": 0},
                 "config": {"model_name": "churn-model", "alias": "champion", "description": "first"}}]
    spec = _pipeline("churn-reg", {"enabled": True}, register, [{"id": "e8", "source": "n4", "target": "r1"}])
    events = await _run(spec, "trk-5")
    assert events[-1].status == "completed", [e for e in events if e.type == "node_finish" and e.status == "error"]
    report = next(e for e in events if e.type == "node_finish" and e.node_id == "r1")
    assert "Registered churn-model version 1, alias @champion" in report.preview["text"]

    mv = _client().get_model_version_by_alias("churn-model", "champion")
    assert mv.description == "first"
    assert mv.run_id == _tracking_event(events)["run_id"]  # registered from the tracked run
    logged = _client().search_logged_models(experiment_ids=[_tracking_event(events)["experiment_id"]])
    assert len(logged) == 1  # not logged a second time


@pytest.mark.asyncio
async def test_register_without_tracking_uses_the_local_store_then_load_it_back():
    register = [{"id": "r1", "type": "mlflow_register", "position": {"x": 5, "y": 0}, "config": {"model_name": "m2", "alias": "prod"}}]
    events = await _run(_pipeline("untracked-reg", None, register, [{"id": "e8", "source": "n4", "target": "r1"}]), "trk-6")
    assert events[-1].status == "completed"
    assert _client().get_experiment_by_name("athena-registry") is not None

    # A second pipeline evaluates the registered model instead of training one.
    spec = _pipeline("load", None)
    spec.nodes[3] = spec.nodes[3].model_copy(update={"type": "mlflow_load", "config": {"model_name": "m2", "alias": "prod"}})
    spec.edges = [e for e in spec.edges if e.target != "n4"]
    events = await _run(spec, "trk-7")
    loaded = next(e for e in events if e.type == "node_finish" and e.node_id == "n4")
    assert loaded.status == "success", loaded.error
    assert "models:/m2@prod" in loaded.preview["summary"]
    assert next(e for e in events if e.node_id == "n5" and e.type == "node_finish").metrics["accuracy"] > 0.5


@pytest.mark.asyncio
async def test_runs_api_lists_tracked_runs():
    from fastapi.testclient import TestClient
    from athena.main import app
    await _run(_pipeline("api-runs", {"enabled": True}), "trk-8")
    body = TestClient(app).get("/api/tracking/runs", params={"experiment": "api-runs"}).json()
    assert len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["status"] == "FINISHED" and "n5.accuracy" in run["metrics"] and run["athena_run_id"] == "trk-8"


def test_registry_nodes_export_mlflow_code():
    spec = _pipeline("export", None,
                     [{"id": "r1", "type": "mlflow_register", "position": {"x": 5, "y": 0}, "config": {"model_name": "m", "alias": "champion"}},
                      {"id": "l1", "type": "mlflow_load", "position": {"x": 6, "y": 0}, "config": {"model_name": "m", "version": "3"}}],
                     [{"id": "e8", "source": "n4", "target": "r1"}])
    code = pipeline_to_python(spec)
    assert "mlflow.register_model(_info_r1.model_uri, 'm')" in code
    assert "set_registered_model_alias('m', 'champion'" in code
    assert "mlflow.sklearn.load_model('models:/m/3')" in code
