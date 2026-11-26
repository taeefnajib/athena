"""MLflow tracking server connector (self-hosted MLflow, Databricks, or any MLflow-compatible server)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, SecretStr

from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui
from athena.tracking.session import INSTALL_HINT, mlflow_installed

if TYPE_CHECKING:
    import pandas as pd


class MlflowConfig(BaseModel):
    tracking_uri: str = "http://localhost:5000"
    registry_uri: str = ""
    username: str = ""
    password: SecretStr = SecretStr("")
    token: SecretStr = SecretStr("")


def _client(cfg: MlflowConfig) -> Any:
    from mlflow import MlflowClient
    return MlflowClient(tracking_uri=cfg.tracking_uri, registry_uri=cfg.registry_uri or cfg.tracking_uri)


@connector(
    "mlflow", label="MLflow Tracking Server", category="tracking",
    description="Log runs and register models on an MLflow server (self-hosted, Databricks, or compatible). "
                "Pipelines can also track to Athena's built-in local store without a connection.",
    library="MLflow", license="Apache-2.0 (MLflow)",
    fields={
        "tracking_uri": ui("Tracking URI", help="e.g. http://mlflow.internal:5000, or databricks"),
        "registry_uri": ui("Registry URI", help="Leave empty to use the tracking URI"),
        "username": ui("Username", help="For servers with basic auth"),
        "password": ui("Password", help="Stored in your OS keychain, or env://VAR"),
        "token": ui("Token", help="Bearer token (MLFLOW_TRACKING_TOKEN). Stored in your OS keychain, or env://VAR"),
    },
    extras={"MLflow client": "pip install 'athena-backend[mlflow]'"},
)
class MlflowConnector(ConnectorBase):
    Config = MlflowConfig

    def test(self, cfg: MlflowConfig) -> TestResult:
        if not mlflow_installed():
            return TestResult(False, INSTALL_HINT)
        from athena.tracking.session import _CRED_ENV  # noqa: PLC0415
        import os
        saved = {k: os.environ.get(k) for k in _CRED_ENV.values()}
        try:
            for field, var in _CRED_ENV.items():
                value = getattr(cfg, field)
                secret = value.get_secret_value() if hasattr(value, "get_secret_value") else value
                if secret:
                    os.environ[var] = secret
            exps = _client(cfg).search_experiments(max_results=1000)
            models = _client(cfg).search_registered_models(max_results=1000)
        except Exception as exc:
            return TestResult(False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return TestResult(True, f"Connected · {len(exps)} experiments · {len(models)} registered models")

    def list(self, cfg: MlflowConfig, path: str | None = None) -> list[Resource]:
        if path is None:
            return [Resource(e.name, e.name, "experiment") for e in _client(cfg).search_experiments()] + \
                   [Resource(f"models:/{m.name}", m.name, "registered_model") for m in _client(cfg).search_registered_models()]
        return []

    def read(self, cfg: MlflowConfig, query: str, limit: int | None = None) -> pd.DataFrame:
        """``query`` is an experiment name; returns its runs (params and metrics as columns)."""
        from athena.tracking.runs import runs_frame
        return runs_frame(_client(cfg), query, limit)
