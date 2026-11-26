"""Experiment tracking: log every run of a tracked pipeline to MLflow, from inside the worker.

A pipeline opts in through ``spec.metadata["tracking"]`` (see :class:`TrackingSettings`). Each run becomes
one MLflow run: node settings as params (``<node_id>.<field>``), node metrics as metrics
(``<node_id>.<metric>``), the pipeline JSON and its exported Python script as artifacts, and every trained
model (outputs typed ``model``) as an MLflow model, so it can be registered later.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from athena.runtime.observers import Emit, register_observer_factory
from athena.tracking.session import Destination, ensure_experiment, mlflow_session

if TYPE_CHECKING:
    from athena.core.handler import HandlerResult
    from athena.schemas.pipeline import NodeSpec, PipelineSpec
    from athena.sdk.node import NodeMeta

MLFLOW_STATUS = {"completed": "FINISHED", "error": "FAILED", "cancelled": "KILLED"}
# MLflow 3's default (skops) refuses common estimators such as tree models; cloudpickle is what
# mlflow.sklearn.load_model has always read. Only load models from registries you trust.
SERIALIZATION = "cloudpickle"


def pip_requirements(model: Any) -> list[str]:
    """What a logged model needs to load: pinned to the versions that trained it. Passing these also
    skips MLflow's requirement inference, which re-imports the model in a subprocess."""
    from importlib.metadata import PackageNotFoundError, version

    pkgs = ["scikit-learn", "cloudpickle", "numpy", "pandas"]
    module = type(model).__module__.split(".")[0]
    pkgs += {"xgboost": ["xgboost"], "lightgbm": ["lightgbm"], "catboost": ["catboost"], "imblearn": ["imbalanced-learn"]}.get(module, [])
    out = []
    for p in pkgs:
        try:
            out.append(f"{p}=={version(p)}")
        except PackageNotFoundError:
            pass
    return out


class TrackingSettings(BaseModel):
    """``spec.metadata["tracking"]``. Travels with the pipeline; refers to a connection by name only."""
    enabled: bool = False
    connection: str = ""        # "" = Athena's local MLflow store
    experiment: str = ""        # "" = the pipeline's name
    log_models: bool = True
    log_code: bool = True


def tracking_settings(spec: PipelineSpec) -> TrackingSettings:
    return TrackingSettings.model_validate(spec.metadata.get("tracking") or {})


class MlflowRunObserver:
    name = "MLflow tracking"

    def __init__(self, settings: TrackingSettings) -> None:
        self.settings = settings
        self._stack = ExitStack()
        self.dest: Destination | None = None
        self.mlflow_run_id: str | None = None
        self.logged_models: dict[int, str] = {}   # id(model object) -> model URI, for Register Model
        self._emit: Emit | None = None

    # -- RunObserver ---------------------------------------------------------------------------
    def on_run_start(self, spec: PipelineSpec, run_id: str, emit: Emit) -> None:
        import mlflow

        self._emit = emit
        self.dest = self._stack.enter_context(mlflow_session(self.settings.connection))
        if not self.settings.connection and not _local_store_exists():
            emit({"type": "run_info", "message": "Creating the local MLflow store (one time, about 20 seconds)…"})
        exp_name = self.settings.experiment or spec.name or "athena"
        exp = ensure_experiment(self.dest, exp_name)
        mlflow.set_experiment(experiment_id=exp.experiment_id)
        labels = {n.id: _label(n.type) for n in spec.nodes}
        run = mlflow.start_run(
            run_name=f"{spec.name} · {datetime.now():%Y-%m-%d %H:%M:%S}",
            tags={"athena.run_id": run_id, "athena.pipeline": spec.name, "mlflow.source.name": "Athena",
                  "athena.node_labels": json.dumps(labels)[:5000]},
        )
        self.mlflow_run_id = run.info.run_id
        params = {f"{n.id}.{k}": _param(v) for n in spec.nodes for k, v in n.config.items()}
        if params:
            mlflow.log_params(params)
        mlflow.log_dict(spec.model_dump(mode="json"), "athena/pipeline.json")
        if self.settings.log_code:
            from athena.core.codegen import pipeline_to_python
            mlflow.log_text(pipeline_to_python(spec), "athena/pipeline.py")
        emit({"type": "run_info", "tracking": {
            "backend": "mlflow", "run_id": run.info.run_id, "experiment": exp_name,
            "experiment_id": exp.experiment_id, "destination": self.dest.display,
            "connection": self.settings.connection, "url": self.dest.run_url(exp.experiment_id, run.info.run_id),
        }})

    def on_node_finish(self, node: NodeSpec, meta: NodeMeta, result: HandlerResult) -> None:
        import mlflow

        metrics = {f"{node.id}.{k}": float(v) for k, v in result.metrics.items() if _finite(v)}
        if metrics:
            mlflow.log_metrics(metrics)
        if not self.settings.log_models:
            return
        for port, out in zip(meta.outputs, result.outputs):
            if port.type == "model" and hasattr(out, "predict") and id(out) not in self.logged_models:
                try:
                    info = mlflow.sklearn.log_model(out, name=node.id, serialization_format=SERIALIZATION,
                                                    pip_requirements=pip_requirements(out))
                except Exception as exc:  # one unloggable model shouldn't stop tracking the rest
                    if self._emit:
                        self._emit({"type": "run_info", "warning": f"Couldn't log the model from {node.id}: {str(exc).splitlines()[0][:200]}"})
                    continue
                self.logged_models[id(out)] = info.model_uri

    def abandon(self, error: str) -> None:
        """Tracking itself failed mid-run: close the MLflow run as FAILED and say why."""
        try:
            import mlflow
            if mlflow.active_run() is not None:
                mlflow.set_tag("athena.tracking_error", error[:5000])
        finally:
            self.on_run_finish("error")

    def on_run_finish(self, status: str) -> None:
        global CURRENT
        try:
            import mlflow
            if mlflow.active_run() is not None:
                mlflow.end_run(status=MLFLOW_STATUS.get(status, "FINISHED"))
        finally:
            self._stack.close()
            CURRENT = None


CURRENT: MlflowRunObserver | None = None
"""The tracking observer of the run in progress (one run per worker process). Used by Register Model."""


def _factory(spec: PipelineSpec) -> MlflowRunObserver | None:
    global CURRENT
    settings = tracking_settings(spec)
    if not settings.enabled:
        return None
    CURRENT = MlflowRunObserver(settings)
    return CURRENT


register_observer_factory(_factory)


def _local_store_exists() -> bool:
    from athena.tracking.session import local_ready
    return local_ready()


def _label(node_type: str) -> str:
    from athena.core.registry import NODE_META
    meta = NODE_META.get(node_type)
    return meta.label if meta else node_type


def _param(v: Any) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s[:500]


def _finite(v: Any) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))
