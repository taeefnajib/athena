"""The subflow library: reusable subflows saved as JSON in ``<data_dir>/subflows/``."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from athena.config import settings
from athena.core.subflows import SubflowConfig


def _dir() -> Path:
    d = settings.data_dir / "subflows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(name: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Give the subflow a name")
    return _dir() / f"{slug}.json"


def list_subflows() -> list[dict[str, Any]]:
    out = []
    for p in sorted(_dir().glob("*.json")):
        try:
            cfg = SubflowConfig.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue  # a hand-edited or partial file: skip it rather than break the library
        out.append({"name": cfg.name, "description": cfg.description, "nodes": len(cfg.nodes),
                    "inputs": [i.type for i in cfg.inputs], "outputs": [o.type for o in cfg.outputs],
                    "config": cfg.model_dump()})
    return sorted(out, key=lambda s: s["name"].lower())


def save_subflow(config: dict[str, Any]) -> dict[str, Any]:
    cfg = SubflowConfig.model_validate(config)
    cfg.check(cfg.name)
    path = _path(cfg.name)
    replaced = path.exists()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg.model_dump(), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return {"name": cfg.name, "path": str(path), "replaced": replaced}


def delete_subflow(name: str) -> None:
    path = _path(name)
    if not path.exists():
        raise FileNotFoundError(f"No saved subflow named {name!r}")
    path.unlink()
