"""Model registry nodes (MLflow): register a trained model, and load a registered one."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from athena.core.handler import ExecutionContext, HandlerResult
from athena.core.registry import register_category
from athena.schemas.artifacts import ModelPreview, TextPreview
from athena.sdk import Port, node, ui
from athena.tracking.observer import SERIALIZATION, pip_requirements

register_category("registry", "Model Registry", "◆")

LOCAL_LABEL = "Local MLflow store (~/.athena/mlflow)"
ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,254}$")


def _code_register(v: dict[str, Any]) -> str:
    alias = (f"mlflow.MlflowClient().set_registered_model_alias({v['model_name']!r}, {v['alias']!r}, _mv_{v['var']}.version)\n"
             if v["alias"] else "")
    return (
        f"# --- Node {v['id']}: Register Model ---\n"
        "import mlflow\n"
        "# Registers into the server in MLFLOW_TRACKING_URI (Athena's local store is sqlite:///<home>/.athena/mlflow/mlflow.db).\n"
        f"with mlflow.start_run(run_name='register {v['model_name']}'):\n"
        f"    _info_{v['var']} = mlflow.sklearn.log_model(model_{v['src']}, name='model', serialization_format='cloudpickle')\n"
        f"_mv_{v['var']} = mlflow.register_model(_info_{v['var']}.model_uri, {v['model_name']!r})\n"
        f"{alias}"
    )


@node(
    "mlflow_register", label="Register Model", category="registry",
    description="Register a trained model in the MLflow Model Registry (the pipeline's tracking server, or the local store)",
    inputs=[Port("model", "model")], outputs=[Port("report", "report")],
    fields={
        "model_name": ui("Registered model name"),
        "alias": ui("Alias", help="Optional, e.g. champion or staging. Moves to this new version."),
        "description": ui("Version description", widget="textarea"),
    },
    code=_code_register,
)
class RegisterModel:
    class Config(BaseModel):
        model_name: str = "athena-model"
        alias: str = ""
        description: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.tracking import observer
        from athena.tracking.session import ensure_experiment, mlflow_session, require_mlflow

        require_mlflow()
        import mlflow
        from mlflow import MlflowClient

        cfg = self.Config(**ctx.config)
        if not cfg.model_name.strip():
            raise ValueError("Enter a registered model name")
        if cfg.alias and not ALIAS_RE.match(cfg.alias):
            raise ValueError("Aliases start with a letter and use letters, digits, '_' or '-'")
        model = ctx.inputs[0] if ctx.inputs else None
        if model is None or not hasattr(model, "predict"):
            raise ValueError("Connect a trained model to this node")

        tracked = observer.CURRENT
        if tracked is not None and tracked.dest is not None and mlflow.active_run() is not None:
            # The pipeline is tracked: register into the same server, inside the run in progress.
            dest = tracked.dest
            uri = tracked.logged_models.get(id(model)) or mlflow.sklearn.log_model(model, name=f"{ctx.node_id}_model", serialization_format=SERIALIZATION,
                                       pip_requirements=pip_requirements(model)).model_uri
            mv = mlflow.register_model(uri, cfg.model_name)
            run_note = f"run {mlflow.active_run().info.run_id[:8]}"
        else:
            with mlflow_session("") as dest:  # untracked pipeline: use the local store
                exp = ensure_experiment(dest, "athena-registry")
                with mlflow.start_run(experiment_id=exp.experiment_id, run_name=f"register {cfg.model_name}",
                                      tags={"athena.run_id": ctx.run_id, "mlflow.source.name": "Athena"}) as run:
                    uri = mlflow.sklearn.log_model(model, name="model", serialization_format=SERIALIZATION,
                                       pip_requirements=pip_requirements(model)).model_uri
                mv = mlflow.register_model(uri, cfg.model_name)
                run_note = f"run {run.info.run_id[:8]} in experiment athena-registry"
        client = MlflowClient(tracking_uri=dest.tracking_uri, registry_uri=dest.registry_uri)
        if cfg.description:
            client.update_model_version(cfg.model_name, mv.version, description=cfg.description)
        if cfg.alias:
            client.set_registered_model_alias(cfg.model_name, cfg.alias, mv.version)
        alias_note = f", alias @{cfg.alias}" if cfg.alias else ""
        text = f"Registered {cfg.model_name} version {mv.version}{alias_note} ({dest.display}, {run_note})."
        ctx.logger.info("Registered model", name=cfg.model_name, version=mv.version, alias=cfg.alias or "-")
        return HandlerResult(outputs=[text], preview=TextPreview(text=text), metrics={"version": float(mv.version)})


def _model_uri(name: str, version: str, alias: str) -> str:
    if alias:
        return f"models:/{name}@{alias}"
    return f"models:/{name}/{version or 'latest'}"


def _code_load(v: dict[str, Any]) -> str:
    return (
        f"# --- Node {v['id']}: Load Registered Model ---\n"
        "import mlflow\n"
        "# Reads from the server in MLFLOW_TRACKING_URI.\n"
        f"model_{v['var']} = mlflow.sklearn.load_model({_model_uri(v['model_name'], v['version'], v['alias'])!r})\n"
    )


@node(
    "mlflow_load", label="Load Registered Model", category="registry",
    description="Load a model from the MLflow Model Registry by alias or version",
    outputs=[Port("model", "model")],
    fields={
        "connection": ui("Registry", widget="connection", connector="mlflow", empty_label=LOCAL_LABEL),
        "model_name": ui("Registered model name"),
        "alias": ui("Alias", help="e.g. champion. Takes precedence over Version."),
        "version": ui("Version", help="A version number, or latest"),
    },
    code=_code_load,
)
class LoadRegisteredModel:
    class Config(BaseModel):
        connection: str = ""
        model_name: str = "athena-model"
        alias: str = ""
        version: str = "latest"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.tracking.session import mlflow_session, require_mlflow

        require_mlflow()
        import mlflow

        cfg = self.Config(**ctx.config)
        uri = _model_uri(cfg.model_name.strip(), cfg.version.strip(), cfg.alias.strip())
        with mlflow_session(cfg.connection) as dest:
            try:
                model = mlflow.sklearn.load_model(uri)
            except Exception as exc:
                raise ValueError(f"Couldn't load {uri} from {dest.display}: {str(exc).splitlines()[0]}") from exc
        ctx.logger.info("Loaded registered model", uri=uri, model=type(model).__name__)
        return HandlerResult(outputs=[model], preview=ModelPreview(summary=f"{uri}\n{model!r}"))
