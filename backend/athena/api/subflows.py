from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from athena.storage.subflows import delete_subflow, list_subflows, save_subflow

router = APIRouter(prefix="/api/subflows")


class SaveSubflow(BaseModel):
    config: dict[str, Any]


@router.get("")
async def index() -> dict[str, Any]:
    return {"subflows": list_subflows()}


@router.put("")
async def save(req: SaveSubflow) -> dict[str, Any]:
    try:
        return save_subflow(req.config)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, detail={"detail": str(exc).splitlines()[0], "code": "SUBFLOW_INVALID"}) from exc


@router.delete("/{name}")
async def delete(name: str) -> dict[str, bool]:
    try:
        delete_subflow(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail={"detail": str(exc), "code": "SUBFLOW_NOT_FOUND"}) from exc
    return {"ok": True}
