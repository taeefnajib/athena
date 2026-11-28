"""Where a node runs: its ``runtime`` (PipelineSpec v2).

- ``None`` / ``"python"``: the run's local worker process (the default).
- ``"ray"``: a Ray task on a local Ray cluster that the worker starts for the run (CPU/GPU/memory from the node's
  ``resources`` are enforced as Ray resources).
- ``"ray:<connection>"``: a Ray task on the cluster of a saved ``ray`` connection.
- ``"k8s:<connection>"``: a Kubernetes Job on the cluster of a saved ``kubernetes`` connection.
- ``"runner:<connection>"``: another machine running ``athena-runner`` (a saved ``runner`` connection).

The engine calls ``run_node`` for every node it executes; caching, retries, timeouts and events stay in the engine,
so a node behaves the same wherever it runs. Runtimes never change exported code: the script runs locally.
"""
from __future__ import annotations

import importlib.util
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult
from athena.schemas.pipeline import NodeSpec

LOCAL = "python"
KINDS = (LOCAL, "ray", "k8s", "runner")
RAY_HINT = "Ray isn't installed: uv pip install 'athena-backend[ray]' (or pip install 'ray[client]')"
K8S_HINT = "The Kubernetes client isn't installed: uv pip install 'athena-backend[k8s]'"
CONNECTOR = {"ray": "ray", "k8s": "kubernetes", "runner": "runner"}  # runtime kind -> connection type
LABEL = {"ray": "Ray cluster", "k8s": "Kubernetes cluster", "runner": "Athena runner"}


class RuntimeUnavailable(ValueError):
    """The node's runtime can't be used here (unknown, not installed, or a missing connection)."""


def parse(runtime: str | None) -> tuple[str, str]:
    """("python" | "ray", connection name or "")."""
    if not runtime:
        return LOCAL, ""
    kind, _, connection = runtime.partition(":")
    kind = kind.strip().lower()
    if kind not in KINDS:
        raise RuntimeUnavailable(f"Unknown runtime {runtime!r}: use python, ray, ray:<connection>, k8s:<connection> or runner:<connection>")
    if kind == LOCAL and connection:
        raise RuntimeUnavailable("The python runtime takes no connection")
    if kind in ("k8s", "runner") and not connection.strip():
        raise RuntimeUnavailable(f"The {kind} runtime needs a {LABEL[kind]} connection: {kind}:<connection>")
    return kind, connection.strip()


def ray_installed() -> bool:
    return importlib.util.find_spec("ray") is not None


def k8s_installed() -> bool:
    return importlib.util.find_spec("kubernetes") is not None


def check(runtime: str | None) -> tuple[str, str]:
    """Validate a runtime before the node runs; raises RuntimeUnavailable with what to do."""
    kind, connection = parse(runtime)
    if kind != LOCAL:
        if kind == "ray" and not ray_installed():
            raise RuntimeUnavailable(RAY_HINT)
        if kind == "k8s" and not k8s_installed():
            raise RuntimeUnavailable(K8S_HINT)
        if connection:
            from athena.connectors.store import get_connection
            try:
                rec = get_connection(connection)
            except Exception as exc:  # a missing connection is a user error
                raise RuntimeUnavailable(f"No saved connection named {connection!r}. Create it under Connections.") from exc
            if rec.get("type") != CONNECTOR[kind]:
                raise RuntimeUnavailable(f"Connection {connection!r} is a {rec.get('label') or rec.get('type')} connection, not a {LABEL[kind]} connection")
    return kind, connection


def run_node(node: NodeSpec, handler: Any, ctx: ExecutionContext) -> HandlerResult:
    kind, connection = check(node.runtime)
    if kind == LOCAL:
        return handler(ctx)  # type: ignore[no-any-return]
    if kind == "k8s":
        from athena.runtime import k8s_runtime
        return k8s_runtime.run(node, ctx, connection)
    if kind == "runner":
        from athena.runtime import runner_runtime
        return runner_runtime.run(node, ctx, connection)
    from athena.runtime import ray_runtime
    return ray_runtime.run(node, ctx, connection)


def available() -> list[dict[str, Any]]:
    """The runtimes the inspector offers: local, local Ray, and each saved Ray / Kubernetes connection."""
    out: list[dict[str, Any]] = [{"value": LOCAL, "label": "Local worker", "available": True, "hint": None}]
    installed = ray_installed()
    out.append({"value": "ray", "label": "Ray (local cluster)", "available": installed, "hint": None if installed else RAY_HINT})
    from athena.connectors.store import list_connections
    k8s = k8s_installed()
    for rec in list_connections():
        if rec.get("type") == "ray":
            out.append({"value": f"ray:{rec['name']}", "label": f"Ray: {rec['name']}", "available": installed,
                        "hint": None if installed else RAY_HINT})
        elif rec.get("type") == "runner":
            out.append({"value": f"runner:{rec['name']}", "label": f"Runner: {rec['name']}", "available": True, "hint": None})
        elif rec.get("type") == "kubernetes":
            out.append({"value": f"k8s:{rec['name']}", "label": f"Kubernetes: {rec['name']}", "available": k8s,
                        "hint": None if k8s else K8S_HINT})
    return out
