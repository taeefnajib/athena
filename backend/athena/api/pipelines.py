import asyncio
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import io

from athena.schemas.pipeline import RunRequest, SaveRequest, LoadRequest, ExportRequest
from athena.core.executor import execute, get_active_run_id
from athena.core.events import broker
from athena.core.dag import has_cycle
from athena.storage.files import save_pipeline, load_pipeline
from athena.storage.autosave import save_autosave, load_latest_autosave
from athena.core.codegen import build_sections, pipeline_to_json, pipeline_to_notebook, pipeline_to_python
from athena.config import settings

router = APIRouter(prefix="/api/pipelines")


@router.post("/run")
async def run_pipeline(req: RunRequest):
    if get_active_run_id() is not None:
        raise HTTPException(409, detail={"detail": "A pipeline is already running", "code": "RUN_ALREADY_IN_PROGRESS"})

    from pydantic import ValidationError

    from athena.core.subflows import expand
    try:  # subflows run as their inner nodes (ids <subflow>.<inner>)
        spec, start_from = expand(req.spec, req.start_from)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, detail={"detail": str(exc).splitlines()[0], "code": "SUBFLOW_INVALID"}) from exc

    nodes_dicts = [{"id": n.id} for n in spec.nodes]
    edges_dicts = [{"source": e.source, "target": e.target} for e in spec.edges]

    if has_cycle(nodes_dicts, edges_dicts):
        raise HTTPException(400, detail={"detail": "Pipeline has a cycle", "code": "PIPELINE_HAS_CYCLE"})

    run_id = str(uuid.uuid4())
    asyncio.create_task(execute(spec, run_id, broker, start_from))
    return {"run_id": run_id}


@router.get("/library")
async def list_library():
    settings.pipelines_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(settings.pipelines_dir.glob("*.athena"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({"name": f.stem, "path": str(f), "modified": f.stat().st_mtime})
    return {"files": files}


@router.post("/save")
async def save(req: SaveRequest):
    try:
        path = req.path.strip()
        # Bare filename (no separators) → save into the pipelines library dir
        if not any(c in path for c in ['/', '\\', ':']):
            name = path if path.endswith(".athena") else f"{path}.athena"
            full_path = str(settings.pipelines_dir / name)
        else:
            full_path = path
        save_pipeline(full_path, req.spec)
        return {"ok": True, "path": full_path}
    except Exception as e:
        raise HTTPException(400, detail={"detail": str(e), "code": "FILE_NOT_WRITABLE"})


@router.post("/load")
async def load(req: LoadRequest):
    try:
        spec = load_pipeline(req.path)
        return {"spec": spec.model_dump()}
    except FileNotFoundError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "FILE_NOT_FOUND"})
    except Exception as e:
        raise HTTPException(400, detail={"detail": str(e), "code": "PIPELINE_VALIDATION_FAILED"})


@router.post("/code")
async def code(req: ExportRequest) -> dict:
    """The generated Python, per node (for the inspector's Code tab) and as the whole script Export Code writes."""
    import anyio

    def build() -> dict:
        sections = build_sections(req.spec)
        return {"script": pipeline_to_python(req.spec),
                "sections": [{"node_id": s.node_id, "label": s.label, "code": s.code, "imports": s.imports,
                              "exported": s.exported} for s in sections]}
    return await anyio.to_thread.run_sync(build)


@router.post("/export")
async def export(req: ExportRequest):
    fmt = req.format.lower()
    if fmt in ("python", "py"):
        content = pipeline_to_python(req.spec)
        filename = "pipeline.py"
        media_type = "text/x-python"
    elif fmt in ("notebook", "ipynb"):
        content = pipeline_to_notebook(req.spec)
        filename = "pipeline.ipynb"
        media_type = "application/x-ipynb+json"
    elif fmt in ("json",):
        content = pipeline_to_json(req.spec)
        filename = "pipeline.json"
        media_type = "application/json"
    elif fmt in ("airflow", "dagster"):
        from athena.core.cron import CronError
        from athena.core.orchestrators import orchestrator_zip
        try:
            data, filename = orchestrator_zip(req.spec, fmt, req.cron)
        except CronError as exc:
            raise HTTPException(400, detail={"detail": str(exc), "code": "CRON_INVALID"}) from exc
        return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    else:
        raise HTTPException(400, detail={"detail": f"Unknown export format {req.format!r} (python, notebook, json, airflow or dagster)",
                                         "code": "EXPORT_FORMAT_UNKNOWN"})

    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/autosave")
async def autosave(req: RunRequest):
    try:
        save_autosave(req.spec)
        return {"ok": True}
    except Exception:
        return {"ok": False}


@router.get("/autosave/latest")
async def get_autosave():
    spec = load_latest_autosave()
    if spec is None:
        raise HTTPException(404, detail={"detail": "No autosave found", "code": "FILE_NOT_FOUND"})
    return {"spec": spec.model_dump()}
