"""Experiment tracking: status, local store setup, and run history for the Runs view."""
from __future__ import annotations

from typing import Any

import anyio
from fastapi import APIRouter, HTTPException

from athena.tracking.session import (INSTALL_HINT, ensure_experiment, local_ready, local_root, mlflow_installed,
                                     mlflow_session)

router = APIRouter(prefix="/api/tracking")


def _require() -> None:
    if not mlflow_installed():
        raise HTTPException(400, detail={"detail": INSTALL_HINT, "code": "MLFLOW_NOT_INSTALLED"})


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(400, detail={"detail": f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}", "code": "TRACKING_FAILED"})


@router.get("/status")
async def status() -> dict[str, Any]:
    version = None
    if mlflow_installed():
        from importlib.metadata import version as pkg_version
        version = pkg_version("mlflow")
    return {"installed": version is not None, "version": version, "install_hint": INSTALL_HINT,
            "local_store": str(local_root()), "local_ready": local_ready()}


@router.post("/local/init")
async def init_local() -> dict[str, Any]:
    """Create the local store ahead of the first tracked run (the one-time setup takes ~20 s)."""
    _require()

    def run() -> None:
        with mlflow_session("") as dest:
            ensure_experiment(dest, "athena")
    try:
        await anyio.to_thread.run_sync(run)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True, "local_store": str(local_root())}


@router.get("/experiments")
async def experiments(connection: str = "") -> dict[str, Any]:
    _require()

    def run() -> list[dict[str, Any]]:
        from mlflow import MlflowClient
        with mlflow_session(connection) as dest:
            client = MlflowClient(tracking_uri=dest.tracking_uri, registry_uri=dest.registry_uri)
            return [{"id": e.experiment_id, "name": e.name} for e in client.search_experiments()]
    if not connection and not local_ready():
        return {"experiments": []}
    try:
        return {"experiments": await anyio.to_thread.run_sync(run)}
    except Exception as exc:
        raise _fail(exc) from exc


@router.get("/runs")
async def runs(experiment: str, connection: str = "", limit: int = 100) -> dict[str, Any]:
    _require()

    def run() -> dict[str, Any]:
        from mlflow import MlflowClient
        from athena.tracking.runs import list_runs
        with mlflow_session(connection) as dest:
            client = MlflowClient(tracking_uri=dest.tracking_uri, registry_uri=dest.registry_uri)
            exp = client.get_experiment_by_name(experiment)
            items = list_runs(client, experiment, min(max(limit, 1), 500))
            return {"runs": items, "destination": dest.display,
                    "experiment_id": exp.experiment_id if exp else None,
                    "ui_url": dest.run_url(exp.experiment_id, "") if exp and dest.ui_url else None}
    if not connection and not local_ready():
        return {"runs": [], "destination": str(local_root()), "experiment_id": None, "ui_url": None}
    try:
        return await anyio.to_thread.run_sync(run)
    except Exception as exc:
        raise _fail(exc) from exc
