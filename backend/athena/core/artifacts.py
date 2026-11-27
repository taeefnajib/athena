"""Node outputs of a finished run, read back from the run's cache folder (written by the worker).

They live in ``<data_dir>/cache/<run_id>/`` until the app shuts down, so the UI can download or profile any
node's output after the run without re-running anything.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from athena.config import settings
from athena.core.cache import ArtifactCache

RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ArtifactNotFound(LookupError):
    pass


def run_dir(run_id: str) -> Path:
    if not RUN_ID.match(run_id):
        raise ArtifactNotFound("Unknown run")
    d = settings.data_dir / "cache" / run_id
    if not d.is_dir():
        raise ArtifactNotFound("This run's results are gone (they are kept until Athena restarts). Run the pipeline again.")
    return d


def load_output(run_id: str, node_id: str, port: int) -> Any:
    d = run_dir(run_id)
    index_path = d / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    if node_id not in index:
        raise ArtifactNotFound(f"Node {node_id!r} has no saved output in this run (it didn't run, or it failed).")
    result = ArtifactCache(d).get(index[node_id])
    if result is None:
        raise ArtifactNotFound(f"Node {node_id!r}'s output couldn't be read back.")
    if not 0 <= port < len(result.outputs):
        raise ArtifactNotFound(f"Node {node_id!r} has no output port {port}.")
    return result.outputs[port]
