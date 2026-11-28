"""Node outputs of a finished run, read back from the run's cache folder (written by the worker).

They live in ``<data_dir>/cache/<run_id>/`` until the app shuts down, so the UI can download or profile any
node's output after the run without re-running anything.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from athena.config import settings
from athena.core.cache import ArtifactCache, read_index, store_dir_for

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


def load_result(run_id: str, node_id: str) -> Any:
    """A node's whole HandlerResult from a finished run (outputs, preview, metrics, replay step)."""
    d = run_dir(run_id)
    index = read_index(d)
    if node_id not in index:
        raise ArtifactNotFound(f"Node {node_id!r} has no saved output in this run (it didn't run, or it failed).")
    result = ArtifactCache(store_dir_for(d)).get(index[node_id])
    if result is None:
        raise ArtifactNotFound(f"Node {node_id!r}'s output is no longer cached. Run the pipeline again.")
    return result


def load_output(run_id: str, node_id: str, port: int) -> Any:
    d = run_dir(run_id)
    index = read_index(d)
    if node_id not in index:
        raise ArtifactNotFound(f"Node {node_id!r} has no saved output in this run (it didn't run, or it failed).")
    result = ArtifactCache(store_dir_for(d)).get(index[node_id])
    if result is None:
        raise ArtifactNotFound(f"Node {node_id!r}'s output is no longer cached (evicted to stay under the cache size limit, "
                               "or it couldn't be saved). Run the pipeline again.")
    if not 0 <= port < len(result.outputs):
        raise ArtifactNotFound(f"Node {node_id!r} has no output port {port}.")
    return result.outputs[port]
