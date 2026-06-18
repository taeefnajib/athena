import hashlib
import json
import pickle
from pathlib import Path
from typing import Any


def _canonical(obj: Any) -> str:
    if isinstance(obj, dict):
        return json.dumps(obj, sort_keys=True, default=str)
    return str(obj)


def compute_cache_key(node_type: str, config: dict, parent_keys: list[str]) -> str:
    payload = f"{node_type}::{_canonical(config)}::{','.join(sorted(parent_keys))}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ArtifactCache:
    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Any | None:
        path = self.dir / f"{key}.pkl"
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        path = self.dir / f"{key}.pkl"
        try:
            with open(path, "wb") as f:
                pickle.dump(value, f)
        except Exception:
            pass

    def clear(self) -> None:
        for f in self.dir.glob("*.pkl"):
            try:
                f.unlink()
            except Exception:
                pass
