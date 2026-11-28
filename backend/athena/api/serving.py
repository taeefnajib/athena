"""Model serving: bundles (package, list, download, delete, build an image), and local endpoints (start, stop, test, metrics)."""
from pathlib import Path
from typing import Any, Literal

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from athena.core.artifacts import ArtifactNotFound
from athena.schemas.pipeline import PipelineSpec, Resources
from athena.serving import builds, endpoints, kserve
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


class KServeRequest(BaseModel):
    connection: str
    image: str = ""  # default: the bundle's last pushed / built image
    min_replicas: int = 1
    max_replicas: int = 1
    resources: Resources | None = None


class BuildRequest(BaseModel):
    target: Literal["docker", "bento", "push"]
    image: str = ""  # docker: the image name (default <slug>:latest); push: what to push (default the last build)


def _bad(exc: Exception, code: str, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"detail": str(exc).splitlines()[0] if str(exc) else type(exc).__name__, "code": code})


@router.get("/bundles")
async def bundles() -> dict[str, Any]:
    def build() -> list[dict[str, Any]]:
        out = []
        for b in list_bundles():
            path = Path(b["path"])
            logs = "--log-requests" in (path / "service.py").read_text(encoding="utf-8")
            out.append({**b, "monitoring": {"logs_requests": logs, "requests_logged": endpoints.logged_requests(path),
                                            "request_log": str(endpoints.request_log(path))},
                        "build": builds.status(b["slug"]), "kserve": kserve.deployment(b["slug"])})
        return out
    items = await anyio.to_thread.run_sync(build)
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
    await anyio.to_thread.run_sync(lambda: builds.cancel(path.name))
    await anyio.to_thread.run_sync(lambda: shutil.rmtree(path))
    return {"ok": True}


@router.get("/tools")
async def build_tools() -> dict[str, Any]:
    """Whether docker / bentoml are installed, for the Build buttons."""
    return await anyio.to_thread.run_sync(builds.tools)


@router.post("/bundles/{slug}/build")
async def start_build(slug: str, req: BuildRequest) -> dict[str, Any]:
    """Build the bundle into a Docker image or a Bento in the background; poll GET for its status and log."""
    try:
        return await anyio.to_thread.run_sync(lambda: builds.start(slug, req.target, req.image))
    except builds.BuildBusy as exc:
        raise _bad(exc, "BUILD_RUNNING", 409) from exc
    except builds.BuildError as exc:
        raise _bad(exc, "BUILD_UNAVAILABLE") from exc
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc


@router.get("/bundles/{slug}/build")
async def build_status(slug: str) -> dict[str, Any] | None:
    return await anyio.to_thread.run_sync(lambda: builds.status(slug))


@router.delete("/bundles/{slug}/build")
async def cancel_build(slug: str) -> dict[str, bool]:
    try:
        await anyio.to_thread.run_sync(lambda: builds.cancel(slug))
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    return {"ok": True}


@router.get("/bundles/{slug}/kserve/manifest", response_class=PlainTextResponse)
async def kserve_manifest(slug: str, image: str = "", namespace: str = "", min_replicas: int = 1,
                          max_replicas: int = 1, connection: str = "") -> PlainTextResponse:
    """The InferenceService as YAML, for kubectl apply (no cluster needed). With ``connection``, its namespace,
    service account and image pull secret are used (it's only read, never contacted)."""
    sa = pull = ""
    if connection:
        from athena.connectors.store import get_connection
        cfg = get_connection(connection)["config"]
        namespace = namespace or cfg.get("namespace", "")
        sa, pull = cfg.get("service_account", ""), cfg.get("image_pull_secret", "")
    try:
        path = bundle_path(slug)
        text = kserve.to_yaml(kserve.manifest(path.name, image or builds.last_image(slug), namespace or "default",
                                              min_replicas, max_replicas, None, sa, pull))
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    except kserve.KServeError as exc:
        raise _bad(exc, "KSERVE_FAILED") from exc
    return PlainTextResponse(text, media_type="application/yaml",
                             headers={"Content-Disposition": f'attachment; filename="{path.name}-inferenceservice.yaml"'})


@router.post("/bundles/{slug}/kserve")
async def kserve_deploy(slug: str, req: KServeRequest) -> dict[str, Any]:
    """Create (or replace) the bundle's InferenceService through a Kubernetes connection."""
    def go() -> dict[str, Any]:
        return kserve.deploy(slug, req.connection, req.image or builds.last_image(slug), req.min_replicas, req.max_replicas, req.resources)
    try:
        return await anyio.to_thread.run_sync(go)
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    except Exception as exc:  # KServeError, a missing connection, the client not installed
        raise _bad(exc, "KSERVE_FAILED") from exc


@router.get("/bundles/{slug}/kserve")
async def kserve_status(slug: str) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(lambda: kserve.status(slug))
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    except Exception as exc:
        raise _bad(exc, "KSERVE_FAILED") from exc


@router.delete("/bundles/{slug}/kserve")
async def kserve_delete(slug: str) -> dict[str, bool]:
    try:
        await anyio.to_thread.run_sync(lambda: kserve.undeploy(slug))
    except BundleError as exc:
        raise _bad(exc, "BUNDLE_NOT_FOUND", 404) from exc
    except Exception as exc:
        raise _bad(exc, "KSERVE_FAILED") from exc
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


@router.get("/endpoints/{slug}/metrics", response_class=PlainTextResponse)
async def metrics(slug: str) -> str:
    """The running endpoint's Prometheus metrics (what a Prometheus server would scrape from its /metrics)."""
    try:
        return await anyio.to_thread.run_sync(lambda: endpoints.metrics(slug))
    except RuntimeError as exc:
        raise _bad(exc, "ENDPOINT_NOT_RUNNING", 409) from exc


@router.post("/endpoints/{slug}/predict")
async def predict(slug: str, body: dict[str, Any]) -> Any:
    """The test console: forwards the request to the running endpoint and returns its answer (errors included)."""
    try:
        code, payload = await anyio.to_thread.run_sync(lambda: endpoints.predict(slug, body))
    except RuntimeError as exc:
        raise _bad(exc, "ENDPOINT_NOT_RUNNING", 409) from exc
    return {"status": code, "response": payload}
