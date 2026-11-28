"""Schedules: list, create/update, delete, run now, and preview a cron expression."""
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from athena.config import settings
from athena.core.cron import CronError, describe, next_times, parse
from athena.scheduling import scheduler
from athena.storage import schedules as store
from athena.storage.files import load_pipeline

router = APIRouter(prefix="/api/schedules")


class ScheduleRequest(BaseModel):
    name: str
    pipeline: str
    cron: str
    enabled: bool = True


def _bad(exc: Exception, code: str, status: int = 400) -> HTTPException:
    msg = exc.errors()[0]["msg"].removeprefix("Value error, ") if isinstance(exc, ValidationError) else str(exc)
    return HTTPException(status, detail={"detail": msg, "code": code})


def _view(s: store.Schedule) -> dict[str, Any]:
    return {**s.model_dump(), "description": describe(parse(s.cron)), "running_run": scheduler.running_run(s.name)}


@router.get("")
async def list_all() -> dict[str, Any]:
    items = await anyio.to_thread.run_sync(store.list_schedules)
    return {"schedules": [_view(s) for s in items], "scheduler_enabled": settings.scheduler}


@router.get("/preview")
async def preview(cron: str) -> dict[str, Any]:
    """What a cron expression means: a description and the next three fire times (local time)."""
    try:
        c = parse(cron)
        return {"description": describe(c), "next": [t.isoformat() for t in next_times(c, store.now())]}
    except CronError as exc:
        raise _bad(exc, "CRON_INVALID") from exc


@router.put("")
async def save(req: ScheduleRequest) -> dict[str, Any]:
    try:
        load_pipeline(req.pipeline)  # it must exist and be a valid pipeline now; it's re-read at every run
    except FileNotFoundError as exc:
        raise _bad(exc, "FILE_NOT_FOUND") from exc
    except (ValueError, ValidationError) as exc:
        raise _bad(ValueError(f"Not a valid pipeline file: {str(exc).splitlines()[0]}"), "PIPELINE_VALIDATION_FAILED") from exc
    try:
        return _view(await anyio.to_thread.run_sync(lambda: store.upsert(req.name, req.pipeline, req.cron, req.enabled)))
    except ValidationError as exc:
        raise _bad(exc, "SCHEDULE_INVALID") from exc


@router.delete("/{name}")
async def remove(name: str) -> dict[str, bool]:
    try:
        await anyio.to_thread.run_sync(lambda: store.delete(name))
    except store.ScheduleError as exc:
        raise _bad(exc, "SCHEDULE_NOT_FOUND", 404) from exc
    return {"ok": True}


@router.get("/{name}/export")
async def export(name: str, target: str = "airflow") -> Response:
    """The schedule as an Airflow DAG or a Dagster job (zip): its saved pipeline, on its cron."""
    from athena.core.orchestrators import orchestrator_zip
    try:
        s = store.get(name)
        data, filename = orchestrator_zip(load_pipeline(s.pipeline), target, s.cron)
    except store.ScheduleError as exc:
        raise _bad(exc, "SCHEDULE_NOT_FOUND", 404) from exc
    except FileNotFoundError as exc:
        raise _bad(exc, "FILE_NOT_FOUND") from exc
    except ValueError as exc:
        raise _bad(exc, "EXPORT_FAILED") from exc
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/{name}/run")
async def run_now(name: str) -> dict[str, str]:
    try:
        return {"run_id": await scheduler.start_run(name, "manual")}
    except scheduler.SlotBusy as exc:
        raise _bad(exc, "RUN_ALREADY_IN_PROGRESS", 409) from exc
    except store.ScheduleError as exc:
        code, status = ("SCHEDULE_NOT_FOUND", 404) if str(exc).startswith("No schedule") else ("SCHEDULE_RUN_FAILED", 400)
        raise _bad(exc, code, status) from exc
