from fastapi import APIRouter
from athena.core.executor import cancel_run, get_active_run_id, reset_active_run

router = APIRouter(prefix="/api/runs")


@router.post("/reset")
async def reset() -> dict[str, bool]:
    """Clear any stuck active-run state. Useful if the frontend reports 409
    after a previous run crashed without releasing its slot."""
    reset_active_run()
    return {"ok": True}


@router.post("/{run_id}/cancel")
async def cancel(run_id: str):
    cancel_run(run_id)
    return {"ok": True}


@router.get("/{run_id}")
async def get_run(run_id: str):
    active = get_active_run_id()
    if active == run_id:
        return {"run_id": run_id, "status": "running"}
    return {"run_id": run_id, "status": "unknown"}
