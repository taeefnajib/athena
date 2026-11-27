"""The pipeline engine: walks the DAG and runs node handlers. Synchronous and process-agnostic.

It runs inside a worker process (see worker.py), never in the API server. Events go out through
``emit`` as plain dicts shaped like the WebSocket protocol (root CLAUDE.md §4.3).
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any, Callable

import structlog

from athena.core.cache import ArtifactCache, compute_cache_key
from athena.core.dag import is_descendant_of, topo_sort
from athena.core.handler import ExecutionContext, HandlerResult
from athena.core.registry import get_handler, get_meta
from athena.runtime.observers import RunObserver, build_observers, notify
from athena.schemas.pipeline import PipelineSpec

Emit = Callable[[dict[str, Any]], None]

LOCAL_RUNTIMES = ("python",)
"""Runtimes the local worker can execute. Distributed ones (ray, k8s, …) arrive in roadmap phase 3."""

_LEVELS = {"debug": "debug", "info": "info", "warning": "warn", "warn": "warn", "error": "error", "exception": "error"}


class NodeLogger:
    """structlog-style logger for handlers: every call becomes a ``node_log`` event (and a log line)."""

    def __init__(self, emit: Emit, node_id: str, base: Any, context: dict[str, Any] | None = None) -> None:
        self._emit, self._node_id, self._base, self._ctx = emit, node_id, base, dict(context or {})

    def bind(self, **kw: Any) -> NodeLogger:
        return NodeLogger(self._emit, self._node_id, self._base, {**self._ctx, **kw})

    def _log(self, method: str, event: str, kw: dict[str, Any]) -> None:
        fields = {**self._ctx, **kw}
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        self._emit({"type": "node_log", "node_id": self._node_id, "level": _LEVELS[method],
                    "msg": f"{event} {detail}".strip()})
        getattr(self._base, "error" if method == "exception" else method)(event, node_id=self._node_id, **fields)

    def debug(self, event: str, **kw: Any) -> None: self._log("debug", event, kw)
    def info(self, event: str, **kw: Any) -> None: self._log("info", event, kw)
    def warning(self, event: str, **kw: Any) -> None: self._log("warning", event, kw)
    def warn(self, event: str, **kw: Any) -> None: self._log("warn", event, kw)
    def error(self, event: str, **kw: Any) -> None: self._log("error", event, kw)
    def exception(self, event: str, **kw: Any) -> None: self._log("exception", event, kw)


def run_spec(
    spec: PipelineSpec,
    run_id: str,
    emit: Emit,
    cancelled: Callable[[], bool],
    cache_dir: Path,
    start_from: list[str] | None = None,
    artifacts_out: dict[tuple[str, int], object] | None = None,
) -> str:
    """Run every node in topological order. Returns the final status (completed | error | cancelled).

    ``artifacts_out``, if given, receives every node output keyed by (node_id, port) (used by tests that
    compare Athena's results with the exported script's)."""
    from athena.plugins import load_plugins
    load_plugins()  # idempotent; the worker has already done it
    base_log = structlog.get_logger().bind(run_id=run_id)
    cache = ArtifactCache(cache_dir)
    nodes_dicts = [{"id": n.id} for n in spec.nodes]
    edges_dicts = [{"source": e.source, "target": e.target} for e in spec.edges]

    observers: list[RunObserver] = []

    def finish(status: str) -> str:
        notify(observers, emit, "on_run_finish", status)  # before run_finish, so tracking is complete
        emit({"type": "run_finish", "status": status})
        return status

    try:
        order = topo_sort(nodes_dicts, edges_dicts)
    except ValueError:
        return finish("error")

    observers = notify(build_observers(spec, emit), emit, "on_run_start", spec, run_id, emit)

    artifacts: dict[tuple[str, int], object] = artifacts_out if artifacts_out is not None else {}
    node_cache_keys: dict[str, str] = {}

    for node_id in order:
        if cancelled():
            return finish("cancelled")
        node = spec.node(node_id)
        if start_from and not is_descendant_of(node_id, start_from, edges_dicts) and node_id not in start_from:
            continue

        inputs: list[object] = []
        for e in spec.edges:
            if e.target == node_id and (e.source, e.source_port) in artifacts:
                while len(inputs) <= e.target_port:
                    inputs.append(None)
                inputs[e.target_port] = artifacts[(e.source, e.source_port)]

        parent_keys = [node_cache_keys.get(e.source, "") for e in spec.edges if e.target == node_id]
        cache_key = compute_cache_key(node.type, node.config, parent_keys)
        node_cache_keys[node_id] = cache_key

        emit({"type": "node_start", "node_id": node_id})
        start = time.monotonic()

        def fail(message: str, tb: str = "") -> str:
            emit({"type": "node_finish", "node_id": node_id, "status": "error",
                  "duration_ms": int((time.monotonic() - start) * 1000),
                  "error": {"message": message, "traceback": tb}})
            base_log.error("node_error", node_id=node_id, error=message)
            return finish("error")

        try:
            handler = get_handler(node.type)
        except KeyError:
            return fail(f"Unknown node type: {node.type!r}")
        if node.runtime not in (None, *LOCAL_RUNTIMES):
            return fail(f"Runtime {node.runtime!r} isn't available in local mode (available: {', '.join(LOCAL_RUNTIMES)})")

        cached = cache.get(cache_key) if node.cache else None
        if cached is not None:
            result: HandlerResult = cached
        else:
            node_log = NodeLogger(emit, node_id, base_log)
            ctx = ExecutionContext(
                node_id=node_id, node_type=node.type, config=dict(node.config), inputs=inputs,
                run_id=run_id, cache_dir=cache_dir,
                logger=node_log,  # type: ignore[arg-type]
                _cancelled=cancelled,
            )
            attempts = node.retry.max_attempts if node.retry else 1
            backoff = node.retry.backoff_s if node.retry else 0.0
            for attempt in range(1, attempts + 1):
                try:
                    result = handler(ctx)
                    break
                except Exception as exc:  # a failing handler is a user-visible error, not a crash
                    if attempt == attempts or cancelled():
                        return fail(str(exc) or type(exc).__name__, traceback.format_exc())
                    wait = backoff * 2 ** (attempt - 1)
                    node_log.warning(f"Attempt {attempt} of {attempts} failed: {exc}. Retrying in {wait:g} s")
                    time.sleep(wait)
            # Always kept for this run (downloads, profiling); node.cache only decides whether it is *reused*.
            cache.set(cache_key, result)
        cache.record(node_id, cache_key)

        for i, art in enumerate(result.outputs):
            artifacts[(node_id, i)] = art
        observers = notify(observers, emit, "on_node_finish", node, get_meta(node.type), result)
        emit({"type": "node_finish", "node_id": node_id, "status": "success",
              "duration_ms": int((time.monotonic() - start) * 1000),
              "preview": result.preview.model_dump() if result.preview else None,
              "metrics": result.metrics})

    return finish("completed")
