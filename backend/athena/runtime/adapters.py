"""Where a node runs: its ``runtime`` (PipelineSpec v2).

- ``None`` / ``"python"``: the run's local worker process (the default).
- ``"ray"``: a Ray task on a local Ray cluster that the worker starts for the run (CPU/GPU/memory from the node's
  ``resources`` are enforced as Ray resources).
- ``"ray:<connection>"``: a Ray task on the cluster of a saved ``ray`` connection.

The engine calls ``run_node`` for every node it executes; caching, retries, timeouts and events stay in the engine,
so a node behaves the same wherever it runs. Runtimes never change exported code: the script runs locally.
"""
from __future__ import annotations

import importlib.util
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult
from athena.schemas.pipeline import NodeSpec

LOCAL = "python"
KINDS = (LOCAL, "ray")
RAY_HINT = "Ray isn't installed: uv pip install 'athena-backend[ray]' (or pip install 'ray[client]')"


class RuntimeUnavailable(ValueError):
    """The node's runtime can't be used here (unknown, not installed, or a missing connection)."""


def parse(runtime: str | None) -> tuple[str, str]:
    """("python" | "ray", connection name or "")."""
    if not runtime:
        return LOCAL, ""
    kind, _, connection = runtime.partition(":")
    kind = kind.strip().lower()
    if kind not in KINDS:
        raise RuntimeUnavailable(f"Unknown runtime {runtime!r}: use python, ray, or ray:<connection>")
    if kind == LOCAL and connection:
        raise RuntimeUnavailable("The python runtime takes no connection")
    return kind, connection.strip()


def ray_installed() -> bool:
    return importlib.util.find_spec("ray") is not None


def check(runtime: str | None) -> tuple[str, str]:
    """Validate a runtime before the node runs; raises RuntimeUnavailable with what to do."""
    kind, connection = parse(runtime)
    if kind == "ray":
        if not ray_installed():
            raise RuntimeUnavailable(RAY_HINT)
        if connection:
            from athena.connectors.store import get_connection
            try:
                rec = get_connection(connection)
            except Exception as exc:  # a missing connection is a user error
                raise RuntimeUnavailable(f"No saved connection named {connection!r}. Create a Ray cluster connection under Connections.") from exc
            if rec.get("type") != "ray":
                raise RuntimeUnavailable(f"Connection {connection!r} is a {rec.get('type')} connection, not a Ray cluster")
    return kind, connection


def run_node(node: NodeSpec, handler: Any, ctx: ExecutionContext) -> HandlerResult:
    kind, connection = check(node.runtime)
    if kind == LOCAL:
        return handler(ctx)  # type: ignore[no-any-return]
    from athena.runtime import ray_runtime
    return ray_runtime.run(node, ctx, connection)


def available() -> list[dict[str, Any]]:
    """The runtimes the inspector offers: local, local Ray, and each saved Ray connection."""
    out: list[dict[str, Any]] = [{"value": LOCAL, "label": "Local worker", "available": True, "hint": None}]
    installed = ray_installed()
    out.append({"value": "ray", "label": "Ray (local cluster)", "available": installed, "hint": None if installed else RAY_HINT})
    from athena.connectors.store import list_connections
    for rec in list_connections():
        if rec.get("type") == "ray":
            out.append({"value": f"ray:{rec['name']}", "label": f"Ray: {rec['name']}", "available": installed,
                        "hint": None if installed else RAY_HINT})
    return out
