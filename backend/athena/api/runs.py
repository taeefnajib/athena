import io
from typing import Any

import anyio
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from athena.core.artifacts import ArtifactNotFound, load_output, load_result
from athena.core.executor import cancel_run, get_active_run_id, reset_active_run

router = APIRouter(prefix="/api/runs")


@router.post("/reset")
async def reset() -> dict[str, bool]:
    """Clear any stuck active-run state. Useful if the frontend reports 409
    after a previous run crashed without releasing its slot."""
    reset_active_run()
    return {"ok": True}


@router.post("/{run_id}/cancel")
async def cancel(run_id: str) -> dict[str, bool]:
    cancel_run(run_id)
    return {"ok": True}


@router.get("/{run_id}")
async def get_run(run_id: str) -> dict[str, str]:
    active = get_active_run_id()
    if active == run_id:
        return {"run_id": run_id, "status": "running"}
    return {"run_id": run_id, "status": "unknown"}


def _missing(exc: ArtifactNotFound) -> HTTPException:
    return HTTPException(404, detail={"detail": str(exc), "code": "ARTIFACT_NOT_FOUND"})


@router.get("/{run_id}/artifacts/{node_id}/{port}")
async def download_artifact(run_id: str, node_id: str, port: int, format: str = "csv") -> Response:
    """A node output from a finished run: tables as CSV or Parquet, models as a joblib file, reports as JSON."""
    def build() -> tuple[bytes, str, str]:
        obj = load_output(run_id, node_id, port)
        if isinstance(obj, pd.Series):
            obj = obj.to_frame()
        if isinstance(obj, pd.DataFrame):
            if format == "parquet":
                buf = io.BytesIO()
                obj.to_parquet(buf)
                return buf.getvalue(), f"{node_id}_{port}.parquet", "application/vnd.apache.parquet"
            return obj.to_csv(index=False).encode(), f"{node_id}_{port}.csv", "text/csv"
        if isinstance(obj, dict):
            import json
            return json.dumps(obj, indent=2, default=str).encode(), f"{node_id}_{port}.json", "application/json"
        if hasattr(obj, "predict") or hasattr(obj, "transform"):
            import joblib
            buf = io.BytesIO()
            joblib.dump(obj, buf)
            return buf.getvalue(), f"{node_id}_model.joblib", "application/octet-stream"
        raise TypeError(f"A {type(obj).__name__} output can't be downloaded")
    try:
        content, filename, media = await anyio.to_thread.run_sync(build)
    except ArtifactNotFound as exc:
        raise _missing(exc) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, detail={"detail": str(exc), "code": "ARTIFACT_NOT_DOWNLOADABLE"}) from exc
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{run_id}/documents/{node_id}/{name}")
async def node_document(run_id: str, node_id: str, name: str, download: bool = False) -> Response:
    """A full HTML report a node produced (Evidently's, for the monitoring nodes).

    It's served sandboxed (CSP ``sandbox allow-scripts``): its scripts run, for the charts, but in an opaque origin
    that can't read Athena's pages or call its API as if it were Athena."""
    def build() -> str:
        result = load_result(run_id, node_id)
        docs = getattr(result, "documents", None) or {}
        if name not in docs:
            raise ArtifactNotFound(f"Node {node_id!r} has no report {name!r} in this run" + (f" (it has: {', '.join(docs)})" if docs else ""))
        return str(docs[name])
    try:
        html = await anyio.to_thread.run_sync(build)
    except ArtifactNotFound as exc:
        raise _missing(exc) from exc
    disposition = "attachment" if download else "inline"
    return Response(html, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-downloads",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'{disposition}; filename="{node_id}_{name}"'})


@router.get("/{run_id}/profile/{node_id}/{port}")
async def profile_artifact(run_id: str, node_id: str, port: int, target: str = "") -> dict[str, Any]:
    """Profile a table produced by a node: schema, statistics, data-quality insights, target association."""
    from athena.profiling import profile_frame

    def build() -> dict[str, Any]:
        obj = load_output(run_id, node_id, port)
        if isinstance(obj, pd.Series):
            obj = obj.to_frame()
        if not isinstance(obj, pd.DataFrame):
            raise TypeError(f"Only tables can be profiled (this output is a {type(obj).__name__})")
        return profile_frame(obj, target or None)
    try:
        return await anyio.to_thread.run_sync(build)
    except ArtifactNotFound as exc:
        raise _missing(exc) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, detail={"detail": str(exc), "code": "PROFILE_FAILED"}) from exc
