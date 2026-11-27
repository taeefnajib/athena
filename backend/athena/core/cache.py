"""Content-addressed artifact cache shared by all runs.

``<data_dir>/cache/store/<key>.pkl`` holds each node's HandlerResult. A key is a hash of the node type, its
config, the keys of its parents and a fingerprint of any local file or folder the config points at, so a node
re-runs when it, anything upstream, or its input file changes, and is reused otherwise. Each run folder
(``<data_dir>/cache/<run_id>/``) keeps an ``index.json`` (node id -> key) so its outputs stay downloadable.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Any

FINGERPRINT_MAX_FILES = 2000


def _canonical(obj: Any) -> str:
    if isinstance(obj, dict):
        return json.dumps(obj, sort_keys=True, default=str)
    return str(obj)


def _path_fingerprint(value: str) -> str | None:
    """size + modification time of a local file, or of the files in a local folder; None if not a path."""
    if not value or len(value) > 1024 or "\n" in value or "://" in value:
        return None
    try:
        p = Path(value).expanduser()
        if p.is_file():
            st = p.stat()
            return f"{p.resolve()}:{st.st_size}:{st.st_mtime_ns}"
        if p.is_dir():
            entries = []
            for i, f in enumerate(sorted(p.rglob("*"))):
                if i >= FINGERPRINT_MAX_FILES:
                    break
                if f.is_file():
                    st = f.stat()
                    entries.append(f"{f.relative_to(p)}:{st.st_size}:{st.st_mtime_ns}")
            return f"{p.resolve()}/" + hashlib.sha256("|".join(entries).encode()).hexdigest()[:16]
    except OSError:
        return None
    return None


def source_fingerprint(config: dict[str, Any]) -> str:
    """Fingerprints of the local paths in a node's config (CSV Loader's file, Model Loader's model, ...)."""
    parts = []
    for key in sorted(config):
        value = config[key]
        if isinstance(value, str):
            fp = _path_fingerprint(value.strip())
            if fp:
                parts.append(f"{key}={fp}")
    return ";".join(parts)


def compute_cache_key(node_type: str, config: dict, parent_keys: list[str], salt: str = "", fingerprint: bool = True) -> str:
    """``salt`` distinguishes otherwise equal keys (a digest of the node's output, or the run id).
    ``fingerprint=False`` skips the local-file fingerprint: for nodes whose paths are outputs, not inputs."""
    fp = source_fingerprint(config) if fingerprint else ""
    payload = f"{node_type}::{_canonical(config)}::{','.join(sorted(parent_keys))}::{fp}::{salt}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ArtifactCache:
    """The shared store. Reading an entry refreshes its timestamp, so eviction drops the least recently used."""

    def __init__(self, store_dir: Path) -> None:
        self.dir = store_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.pkl"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                value = pickle.load(f)
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError):
            return None
        try:
            os.utime(path)
        except OSError:
            pass  # a read-only store still serves hits; it just can't track recency
        return value

    def set(self, key: str, value: Any) -> bool:
        """Store a result; False if it can't be pickled (it then simply isn't cached)."""
        path, tmp = self._path(key), self._path(key).with_suffix(".tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump(value, f)
            os.replace(tmp, path)  # atomic: a crash mid-write never leaves a truncated entry
            return True
        except (OSError, pickle.PicklingError, TypeError, AttributeError):
            tmp.unlink(missing_ok=True)
            return False

    def evict(self, max_bytes: int, keep: set[str] = frozenset()) -> int:  # type: ignore[assignment]
        """Delete least-recently-used entries until the store is under ``max_bytes``. Returns bytes freed."""
        entries = []
        for p in self.dir.glob("*.pkl"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, p))
        total = sum(size for _, size, _ in entries)
        freed = 0
        for _, size, p in sorted(entries):
            if total - freed <= max_bytes:
                break
            if p.stem in keep:
                continue
            try:
                p.unlink()
                freed += size
            except OSError:
                continue
        return freed


def store_dir_for(run_dir: Path) -> Path:
    """Runs live in ``cache/<run_id>``; the shared store is their sibling ``cache/store``."""
    return run_dir.parent / "store"


def record(run_dir: Path, node_id: str, key: str) -> None:
    """Remember which store entry holds a node's outputs in this run (for downloads and profiling)."""
    index_path = run_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    index[node_id] = key
    index_path.write_text(json.dumps(index), encoding="utf-8")


def read_index(run_dir: Path) -> dict[str, str]:
    index_path = run_dir / "index.json"
    return json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
