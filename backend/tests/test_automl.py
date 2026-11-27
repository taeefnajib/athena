"""AutoML Search (FLAML): task/metric resolution, the search itself, pipelines, tracking and export."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog

pytest.importorskip("flaml")

import athena.core.executor as exe  # noqa: E402
from athena.core.codegen import pipeline_to_python  # noqa: E402
from athena.core.events import EventBroker  # noqa: E402
from athena.core.handler import ExecutionContext  # noqa: E402
from athena.nodes.automl import AutoMLHandler, infer_task, resolve_metric  # noqa: E402
from athena.schemas.pipeline import PipelineSpec  # noqa: E402

DATA_CSV = str(Path(__file__).parents[1] / "data.csv")
FAST = {"time_budget": 3, "estimators": "rf, extra_tree", "random_state": 0}


def _ctx(tmp_path: Path, config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="a1", node_type="automl", config=config, inputs=inputs,
                            run_id="r", cache_dir=tmp_path, logger=structlog.get_logger())


def _clf(n: int = 300, classes: int = 2) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(n, 4)), columns=list("abcd"))
    y = pd.Series(pd.cut(X["a"] + X["b"], classes, labels=False).astype(int), name="target")
    return X, y


def test_task_inference():
    assert infer_task(pd.Series([0, 1, 1, 0] * 20)) == "classification"
    assert infer_task(pd.Series(["yes", "no"] * 20)) == "classification"
    assert infer_task(pd.Series(np.linspace(0, 1, 200))) == "regression"


def test_metric_resolution_and_mismatch():
    assert resolve_metric("auto", "classification", 2) == "roc_auc"
    assert resolve_metric("auto", "classification", 4) == "log_loss"
    assert resolve_metric("auto", "regression", 0) == "r2"
    assert resolve_metric("f1", "classification", 3) == "macro_f1"
    with pytest.raises(ValueError, match="classification metric"):
        resolve_metric("accuracy", "regression", 0)


def test_search_returns_a_working_model_and_a_leaderboard(tmp_path: Path):
    X, y = _clf()
    result = AutoMLHandler()(_ctx(tmp_path, {**FAST, "metric": "accuracy"}, [X, y]))
    model, board = result.outputs
    assert (model.predict(X.head(10)) == y.head(10)).mean() >= 0.7
    assert set(board["model_family"]) <= {"rf", "extra_tree"} and board["winner"].sum() == 1
    assert board.iloc[0]["winner"]  # sorted best first
    assert 0.7 <= result.metrics["best_accuracy"] <= 1 and result.metrics["trials"] >= 1
    assert result.preview.kind == "dataframe"


def test_regression_is_inferred(tmp_path: Path):
    X, _ = _clf()
    y = pd.Series(X["a"] * 3 + X["c"], name="target")
    result = AutoMLHandler()(_ctx(tmp_path, FAST, [X, y]))
    assert "best_r2" in result.metrics and result.metrics["best_r2"] > 0.5


def test_unknown_model_family_is_a_clear_error(tmp_path: Path):
    X, y = _clf()
    with pytest.raises(ValueError, match="AutoML search failed"):
        AutoMLHandler()(_ctx(tmp_path, {**FAST, "estimators": "not_a_model"}, [X, y]))


def _pipeline(tracking: dict | None = None) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "automl-demo", "metadata": {"tracking": tracking} if tracking else {}, "nodes": [
        {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": DATA_CSV}},
        {"id": "n2", "type": "imputer", "position": {"x": 1, "y": 0}, "config": {}},
        {"id": "n3", "type": "train_test", "position": {"x": 2, "y": 0}, "config": {}},
        {"id": "n4", "type": "automl", "position": {"x": 3, "y": 0}, "config": FAST},
        {"id": "n5", "type": "metrics", "position": {"x": 4, "y": 0}, "config": {}},
    ], "edges": [
        {"id": "e1", "source": "n1", "target": "n2"}, {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "target": "n4", "source_port": 0, "target_port": 0},
        {"id": "e4", "source": "n3", "target": "n4", "source_port": 1, "target_port": 1},
        {"id": "e5", "source": "n4", "target": "n5", "source_port": 0, "target_port": 0},
        {"id": "e6", "source": "n3", "target": "n5", "source_port": 2, "target_port": 1},
        {"id": "e7", "source": "n3", "target": "n5", "source_port": 3, "target_port": 2},
    ]})


async def _run(spec: PipelineSpec, run_id: str) -> list:
    broker = EventBroker()
    q = broker.subscribe(run_id)
    await exe.execute(spec, run_id, broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    return events


@pytest.mark.asyncio
async def test_automl_in_a_pipeline_feeds_the_metrics_node():
    events = await _run(_pipeline(), "automl-run")
    assert events[-1].status == "completed", [e.error for e in events if e.type == "node_finish" and e.status == "error"]
    metrics = next(e for e in events if e.type == "node_finish" and e.node_id == "n5").metrics
    assert metrics["accuracy"] > 0.8
    logs = [e.msg for e in events if e.type == "node_log" and e.node_id == "n4"]
    assert any(m.startswith("Best model") for m in logs) and any("List of ML learners" in m for m in logs)


@pytest.mark.asyncio
async def test_tracked_automl_logs_its_leaderboard(mlflow_local_store):
    import mlflow
    from athena.tracking.session import local_uri
    events = await _run(_pipeline({"enabled": True}), "automl-tracked")
    assert events[-1].status == "completed"
    run_id = next(e.tracking["run_id"] for e in events if e.type == "run_info" and e.tracking)
    client = mlflow.MlflowClient(tracking_uri=local_uri())
    paths = {a.path for a in client.list_artifacts(run_id, "athena")}
    assert "athena/n4_automl_leaderboard.json" in paths
    run = client.get_run(run_id)
    assert run.data.params["n4.best.family"] in {"rf", "extra_tree"}
    assert "n4.best_roc_auc" in run.data.metrics


def test_export_uses_flaml():
    code = pipeline_to_python(_pipeline())
    assert "from flaml import AutoML" in code
    assert "estimator_list=['rf', 'extra_tree']" in code and "time_budget=3" in code
