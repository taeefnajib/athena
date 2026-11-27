"""Saved connections: ``<data_dir>/connections.json`` holds non-secret settings plus, for each secret
field, a marker ("keychain" or "env://VAR"). The secret values themselves live in secrets.py's store.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr, ValidationError

from athena.config import settings
from athena.connectors import secrets
from athena.connectors.registry import get_connector

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
KEYCHAIN = "keychain"


class ConnectionError_(ValueError):
    """A user-facing problem with a connection (bad name, unknown type, invalid settings)."""


def _path() -> Path:
    return settings.data_dir / "connections.json"


def _read() -> dict[str, dict[str, Any]]:
    p = _path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("connections", {})


def _write(conns: dict[str, dict[str, Any]]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "connections": conns}, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _public(name: str, rec: dict[str, Any]) -> dict[str, Any]:
    meta, _ = get_connector(rec["type"]) if _known(rec["type"]) else (None, None)
    return {
        "name": name,
        "type": rec["type"],
        "label": meta.label if meta else rec["type"],
        "config": rec["config"],
        # For each secret field: is it set, and is it an env:// reference (shown) or a keychain entry (never shown)?
        "secrets": {f: {"set": True, "ref": m if m.startswith(secrets.ENV_PREFIX) else None}
                    for f, m in rec.get("secrets", {}).items()},
        "updated": rec.get("updated"),
        "known_type": meta is not None,
    }


def _known(conn_type: str) -> bool:
    try:
        get_connector(conn_type)
        return True
    except KeyError:
        return False


def list_connections() -> list[dict[str, Any]]:
    return [_public(n, r) for n, r in sorted(_read().items())]


def get_connection(name: str) -> dict[str, Any]:
    conns = _read()
    if name not in conns:
        raise ConnectionError_(f"No saved connection named {name!r}")
    return _public(name, conns[name])


def _split(conn_type: str, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate config; return (non-secret values, raw secret inputs)."""
    meta, _ = get_connector(conn_type)
    secret_fields = set(meta.secret_fields)
    plain = {k: v for k, v in config.items() if k not in secret_fields and k in meta.config.model_fields}
    raw_secrets = {k: str(config.get(k) or "") for k in secret_fields}
    try:
        validated = meta.config(**plain)
    except ValidationError as exc:
        raise ConnectionError_(f"Invalid settings: {exc.errors()[0]['loc'][0]}: {exc.errors()[0]['msg']}") from exc
    return {k: v for k, v in validated.model_dump().items() if k not in secret_fields}, raw_secrets


def save_connection(name: str, conn_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Create or update. An empty secret input keeps the saved secret; ``env://VAR`` stores a reference."""
    if not NAME_RE.match(name):
        raise ConnectionError_("Connection names use letters, digits, '.', '_' or '-' (max 64), starting with a letter or digit")
    try:
        plain, raw = _split(conn_type, config)
    except KeyError as exc:
        raise ConnectionError_(str(exc)) from exc
    conns = _read()
    existing = conns.get(name, {})
    if existing and existing.get("type") != conn_type:
        raise ConnectionError_(f"{name!r} is already a {existing['type']} connection")
    markers = dict(existing.get("secrets", {}))
    for field, value in raw.items():
        if value == "":
            continue  # keep whatever is saved (or nothing)
        if value.startswith(secrets.ENV_PREFIX):
            secrets.get_store().delete(secrets.secret_key(name, field))
            markers[field] = value
        else:
            secrets.get_store().set(secrets.secret_key(name, field), value)
            markers[field] = KEYCHAIN
    conns[name] = {"type": conn_type, "config": plain, "secrets": markers,
                   "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(conns)
    return _public(name, conns[name])


def delete_connection(name: str) -> None:
    conns = _read()
    rec = conns.pop(name, None)
    if rec is None:
        raise ConnectionError_(f"No saved connection named {name!r}")
    for field in rec.get("secrets", {}):
        secrets.get_store().delete(secrets.secret_key(name, field))
    _write(conns)


def build_config(conn_type: str, config: dict[str, Any], name: str | None = None) -> BaseModel:
    """A ready-to-use Config: from form values (testing before saving), falling back to the saved
    secrets of connection ``name`` for secret fields left empty."""
    meta, _ = get_connector(conn_type)
    plain, raw = _split(conn_type, config)
    saved = _read().get(name or "", {}).get("secrets", {})
    resolved: dict[str, Any] = dict(plain)
    for field, value in raw.items():
        if value.startswith(secrets.ENV_PREFIX):
            resolved[field] = SecretStr(secrets.resolve(value, name or "(unsaved)", field))
        elif value:
            resolved[field] = SecretStr(value)
        elif field in saved:
            resolved[field] = SecretStr(secrets.resolve(saved[field], name or "", field))
    return meta.config(**resolved)


def resolve_connection(name: str) -> tuple[Any, BaseModel]:
    """(connector implementation, Config with secrets) for a saved connection. Used by nodes in the worker."""
    conns = _read()
    if name not in conns:
        raise ConnectionError_(f"No saved connection named {name!r}. Create it under Connections.")
    rec = conns[name]
    _, impl = get_connector(rec["type"])
    cfg = build_config(rec["type"], dict(rec["config"]), name)
    return impl, cfg
