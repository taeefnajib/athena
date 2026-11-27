"""Connectors (what Athena can talk to) and connections (the user's saved, named configurations)."""
from __future__ import annotations

from typing import Any

import anyio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from athena.connectors.registry import CONNECTOR_META, get_connector
from athena.connectors.store import (ConnectionError_, build_config, delete_connection, get_connection,
                                     list_connections, resolve_connection, save_connection)
from athena.plugins import load_plugins, plugin_report
from athena.sdk.connector import connector_spec

load_plugins()
router = APIRouter(prefix="/api")


class ConnectionIn(BaseModel):
    name: str
    type: str
    config: dict[str, Any] = {}


class TestIn(BaseModel):
    type: str
    config: dict[str, Any] = {}
    name: str | None = None
    """Saved connection whose stored secrets fill in any secret fields left empty."""


def _bad(exc: Exception, code: str = "CONNECTION_INVALID") -> HTTPException:
    return HTTPException(400, detail={"detail": str(exc), "code": code})


@router.get("/connectors")
async def connectors() -> dict[str, Any]:
    return {"connectors": [connector_spec(m) for m in CONNECTOR_META.values()]}


@router.get("/plugins")
async def plugins() -> dict[str, Any]:
    return {"plugins": plugin_report()}


@router.get("/connections")
async def connections() -> dict[str, Any]:
    return {"connections": list_connections()}


@router.put("/connections")
async def put_connection(body: ConnectionIn) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(save_connection, body.name, body.type, body.config)
    except (ConnectionError_, RuntimeError) as exc:
        raise _bad(exc) from exc


@router.delete("/connections/{name}")
async def remove_connection(name: str) -> dict[str, bool]:
    try:
        delete_connection(name)
    except ConnectionError_ as exc:
        raise HTTPException(404, detail={"detail": str(exc), "code": "CONNECTION_NOT_FOUND"}) from exc
    return {"ok": True}


@router.post("/connections/test")
async def test_connection(body: TestIn) -> dict[str, Any]:
    """Test settings from the form (before or after saving). Never raises for an unreachable server:
    the result says what went wrong."""
    def run() -> dict[str, Any]:
        try:
            _, impl = get_connector(body.type)
            cfg = build_config(body.type, body.config, body.name)
            r = impl.test(cfg)
            return {"ok": r.ok, "message": r.message, "details": r.details}
        except (ConnectionError_, RuntimeError, ValueError, KeyError) as exc:
            return {"ok": False, "message": str(exc), "details": {}}
    return await anyio.to_thread.run_sync(run)


@router.get("/connections/{name}")
async def one_connection(name: str) -> dict[str, Any]:
    try:
        return get_connection(name)
    except ConnectionError_ as exc:
        raise HTTPException(404, detail={"detail": str(exc), "code": "CONNECTION_NOT_FOUND"}) from exc


@router.get("/connections/{name}/resources")
async def resources(name: str, path: str | None = None) -> dict[str, Any]:
    def run() -> list[dict[str, Any]]:
        impl, cfg = resolve_connection(name)
        return [r.__dict__ for r in impl.list(cfg, path)]
    try:
        return {"resources": await anyio.to_thread.run_sync(run)}
    except Exception as exc:  # unreachable server, bad credentials: tell the user, don't 500
        raise _bad(exc, "CONNECTION_FAILED") from exc
