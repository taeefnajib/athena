"""Model serving: bundles (build, list, download, delete) and local endpoints (start, stop, test)."""
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from athena.core.artifacts import ArtifactNotFound
from athena.schemas.pipeline import PipelineSpec
from athena.serving import endpoints
from athena.serving.bundle import (
    BundleError,
    bundle_from_run,
    bundle_path,
    list_bundles,
    zip_bundle,
)

router = APIRouter(prefix="/api/serving")


class BundleRequest(BaseModel):
    name: str
    spec: PipelineSpec
    run_id: str
    node_id: str
    port: int = 0


def _bad(exc: Exception, code: str, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"detail": str(exc).splitlines()[0] if str(exc) else type(exc).__name__, "code": code})


@router.get("/bundles")
async def bundles() -> dict[str, Any]:
    items = await anyio.to_thread.run_sync(list_bundles)
    live = endpoints.running()
    return {"bundles": [{**b, "endpoint": live.get(b["slug"], {"running": False, "url": None})} for b in items]}


@router.post("/bundles")
async def create(req: BundleRequest) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(lambda: bundle_from_run(req.name, req.spec, req.run_id, req.node_id, req.port))
    except ArtifactNotFound as exc:
        raise _bad(exc, "ARTIFACT_NOT_FOUND", 404) from exc
    except (BundleError, TypeError) as exc:
        raise _bad(exc, "BUNDLE_FAILED") from exc


@router.get("/bundles/{slug}/download")
async def download(slug: str) -> Response:
    try:
        data = await anyio.to_thread.run_sync(lambda: zip_bundle(slug))
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'})


@router.delete("/bundles/{slug}")
async def delete(slug: str) -> dict[str, bool]:
    import shutil
    try:
        path = bundle_path(slug)
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    endpoints.stop(path.name)
    await anyio.to_thread.run_sync(lambda: shutil.rmtree(path))
    return {"ok": True}


@router.post("/endpoints/{slug}")
async def start(slug: str) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(lambda: endpoints.start(slug))
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    except RuntimeError as exc:
        raise _bad(exc, "ENDPOINT_FAILED", 500) from exc


@router.delete("/endpoints/{slug}")
async def stop(slug: str) -> dict[str, bool]:
    await anyio.to_thread.run_sync(lambda: endpoints.stop(slug))
    return {"ok": True}


@router.post("/endpoints/{slug}/predict")
async def predict(slug: str, body: dict[str, Any]) -> Any:
    """The test console: forwards the request to the running endpoint and returns its answer (errors included)."""
    try:
        code, payload = await anyio.to_thread.run_sync(lambda: endpoints.predict(slug, body))
    except RuntimeError as exc:
        raise _bad(exc, "ENDPOINT_NOT_RUNNING", 409) from exc
    return {"status": code, "response": payload}
