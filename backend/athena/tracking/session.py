"""Point MLflow at a destination: Athena's local store, or a saved ``mlflow`` connection.

MLflow keeps its tracking URI and credentials in process-global state (and environment variables),
so every use goes through ``mlflow_session``, which sets them and restores the previous values.
The local store is a SQLite database plus an artifact folder under ``<data_dir>/mlflow`` and needs
the full ``mlflow`` package (``pip install 'athena-backend[mlflow]'``).
"""
from __future__ import annotations

import importlib.util
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from athena.config import settings

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")  # MLflow prints a tooling hint on import otherwise

INSTALL_HINT = "MLflow isn't installed. Run: pip install 'athena-backend[mlflow]' (in backend/: uv sync --extra mlflow)"
_lock = threading.RLock()  # the API server may serve several tracking requests at once
_CRED_ENV = {"username": "MLFLOW_TRACKING_USERNAME", "password": "MLFLOW_TRACKING_PASSWORD", "token": "MLFLOW_TRACKING_TOKEN"}


def mlflow_installed() -> bool:
    return importlib.util.find_spec("mlflow") is not None


def require_mlflow() -> None:
    if not mlflow_installed():
        raise RuntimeError(INSTALL_HINT)


def local_root() -> Path:
    return settings.data_dir / "mlflow"


def local_db() -> Path:
    return local_root() / "mlflow.db"


def local_uri() -> str:
    return "sqlite:///" + local_db().as_posix()


def local_ready() -> bool:
    return local_db().exists()


@dataclass
class Destination:
    connection: str            # "" = local store
    tracking_uri: str
    registry_uri: str
    artifact_root: Path | None  # only for the local store: where new experiments keep artifacts
    display: str               # what to show users
    ui_url: str | None         # base URL of an MLflow UI, if the server has one

    def run_url(self, experiment_id: str, run_id: str) -> str | None:
        return f"{self.ui_url.rstrip('/')}/#/experiments/{experiment_id}/runs/{run_id}" if self.ui_url else None


def _resolve(connection: str) -> tuple[Destination, dict[str, str]]:
    if not connection:
        root = local_root()
        root.mkdir(parents=True, exist_ok=True)
        return Destination("", local_uri(), local_uri(), root / "artifacts", f"Local store ({root})", None), {}
    from athena.connectors.store import resolve_connection
    _, cfg = resolve_connection(connection)
    uri = cfg.tracking_uri.strip()
    if not uri:
        raise ValueError(f"Connection {connection!r} has no tracking URI")
    env = {}
    for field, var in _CRED_ENV.items():
        value = getattr(cfg, field)
        secret = value.get_secret_value() if hasattr(value, "get_secret_value") else value
        if secret:
            env[var] = secret
    ui = uri if uri.startswith(("http://", "https://")) else None
    return Destination(connection, uri, cfg.registry_uri.strip() or uri, None, uri, ui), env


@contextmanager
def mlflow_session(connection: str = "") -> Iterator[Destination]:
    """Use MLflow against ``connection`` ("" = local store) for the duration of the block."""
    require_mlflow()
    import mlflow

    dest, env = _resolve(connection)
    with _lock:
        prev_uri, prev_reg = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
        prev_env = {k: os.environ.get(k) for k in _CRED_ENV.values()}
        try:
            for var in _CRED_ENV.values():
                os.environ.pop(var, None)
            os.environ.update(env)
            mlflow.set_tracking_uri(dest.tracking_uri)
            mlflow.set_registry_uri(dest.registry_uri)
            yield dest
        finally:
            mlflow.set_tracking_uri(prev_uri)
            mlflow.set_registry_uri(prev_reg)
            for k, v in prev_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def ensure_experiment(dest: Destination, name: str) -> Any:
    """Get or create an experiment; local experiments keep artifacts under <data_dir>/mlflow/artifacts."""
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=dest.tracking_uri, registry_uri=dest.registry_uri)
    exp = client.get_experiment_by_name(name)
    if exp is None:
        location = (dest.artifact_root / _safe(name)).as_uri() if dest.artifact_root else None
        client.create_experiment(name, artifact_location=location)
        exp = client.get_experiment_by_name(name)
    return exp


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "experiment"
