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
from athena.core.codegen import pipeline_to_python, pipeline_to_json
from athena.config import settings

router = APIRouter(prefix="/api/pipelines")


@router.post("/run")
async def run_pipeline(req: RunRequest):
    if get_active_run_id() is not None:
        raise HTTPException(409, detail={"detail": "A pipeline is already running", "code": "RUN_ALREADY_IN_PROGRESS"})

    nodes_dicts = [{"id": n.id} for n in req.spec.nodes]
    edges_dicts = [{"source": e.source, "target": e.target} for e in req.spec.edges]

    if has_cycle(nodes_dicts, edges_dicts):
        raise HTTPException(400, detail={"detail": "Pipeline has a cycle", "code": "PIPELINE_HAS_CYCLE"})

    run_id = str(uuid.uuid4())
    asyncio.create_task(execute(req.spec, run_id, broker, req.start_from))
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


@router.post("/export")
async def export(req: ExportRequest):
    fmt = req.format.lower()
    if fmt in ("python", "py"):
        content = pipeline_to_python(req.spec)
        filename = "pipeline.py"
        media_type = "text/x-python"
    elif fmt in ("json",):
        content = pipeline_to_json(req.spec)
        filename = "pipeline.json"
        media_type = "application/json"
    else:
        content = pipeline_to_json(req.spec)
        filename = "pipeline.json"
        media_type = "application/json"

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
