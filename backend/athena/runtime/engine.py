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

from athena.core.cache import ArtifactCache, compute_cache_key, record, store_dir_for
from athena.core.dag import topo_sort
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
    from athena.config import settings
    from athena.plugins import load_plugins
    load_plugins()  # idempotent; the worker has already done it
    base_log = structlog.get_logger().bind(run_id=run_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = ArtifactCache(store_dir_for(cache_dir))
    nodes_dicts = [{"id": n.id} for n in spec.nodes]
    edges_dicts = [{"source": e.source, "target": e.target} for e in spec.edges]
    known = {n.id for n in spec.nodes}
    # Run from selected: force the chosen nodes and everything downstream; run (or reuse) only their ancestors.
    forced = _reachable({i for i in (start_from or []) if i in known}, edges_dicts, downstream=True)
    needed = forced | _reachable(forced, edges_dicts, downstream=False) if start_from else None
    used_keys: set[str] = set()

    observers: list[RunObserver] = []

    def finish(status: str) -> str:
        notify(observers, emit, "on_run_finish", status)  # before run_finish, so tracking is complete
        emit({"type": "run_finish", "status": status})
        cache.evict(int(settings.cache_max_gb * 1e9), keep=used_keys)
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
        if needed is not None and node_id not in needed:
            continue

        inputs: list[object] = []
        for e in spec.edges:
            if e.target == node_id and (e.source, e.source_port) in artifacts:
                while len(inputs) <= e.target_port:
                    inputs.append(None)
                inputs[e.target_port] = artifacts[(e.source, e.source_port)]

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
            meta = get_meta(node.type)
        except KeyError:
            return fail(f"Unknown node type: {node.type!r}")
        if node.runtime not in (None, *LOCAL_RUNTIMES):
            return fail(f"Runtime {node.runtime!r} isn't available in local mode (available: {', '.join(LOCAL_RUNTIMES)})")

        # Reusable nodes are skipped when their key is cached. The others (side effects, live data, cache off)
        # always execute; their key is then salted with a digest of what they produced, so downstream nodes
        # recompute exactly when that output changed (a query returning the same rows keeps them cached).
        reusable = node.cache and meta.reusable
        parent_keys = [node_cache_keys.get(e.source, "") for e in spec.edges if e.target == node_id]
        cache_key = compute_cache_key(node.type, node.config, parent_keys)
        node_log = NodeLogger(emit, node_id, base_log)

        hit = cache.get(cache_key) if reusable and node_id not in forced else None
        if hit is not None:
            result: HandlerResult = hit
            node_log.info("Reused the result of an earlier run: settings, upstream nodes and input files are unchanged")
        else:
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
            if not reusable:
                # keyed by what it produced; no file fingerprint (an export's path is its output, not an input)
                cache_key = compute_cache_key(node.type, node.config, parent_keys, salt=_digest(result.outputs) or run_id,
                                              fingerprint=False)
            # Stored even when not reusable: this run's outputs stay downloadable and profilable.
            cache.set(cache_key, result)
        node_cache_keys[node_id] = cache_key
        record(cache_dir, node_id, cache_key)
        used_keys.add(cache_key)

        for i, art in enumerate(result.outputs):
            artifacts[(node_id, i)] = art
        observers = notify(observers, emit, "on_node_finish", node, meta, result)
        emit({"type": "node_finish", "node_id": node_id, "status": "success",
              "duration_ms": int((time.monotonic() - start) * 1000),
              "preview": result.preview.model_dump() if result.preview else None,
              "metrics": result.metrics, "cached": hit is not None})

    return finish("completed")


def _reachable(start: set[str], edges: list[dict[str, str]], downstream: bool) -> set[str]:
    """``start`` plus every node reachable from it, following edges downstream or upstream."""
    src, dst = ("source", "target") if downstream else ("target", "source")
    seen, frontier = set(start), list(start)
    while frontier:
        current = frontier.pop()
        for e in edges:
            if e[src] == current and e[dst] not in seen:
                seen.add(e[dst])
                frontier.append(e[dst])
    return seen


def _digest(outputs: list[Any]) -> str | None:
    """A fingerprint of a node's outputs by content (equal tables give equal digests however they were made),
    or None if an output can't be fingerprinted."""
    import hashlib
    import pickle

    import numpy as np
    import pandas as pd

    h = hashlib.sha256()
    try:
        for out in outputs:
            if isinstance(out, (pd.DataFrame, pd.Series)):
                frame = out.to_frame() if isinstance(out, pd.Series) else out
                h.update(repr([(str(c), str(t)) for c, t in frame.dtypes.items()]).encode())
                try:
                    rows = pd.util.hash_pandas_object(frame, index=True)
                except TypeError:  # unhashable cells (lists, dicts)
                    rows = pd.util.hash_pandas_object(frame.astype(str), index=True)
                h.update(rows.to_numpy().tobytes())
            elif isinstance(out, np.ndarray) and out.dtype != object:
                h.update(f"{out.dtype}{out.shape}".encode())
                h.update(np.ascontiguousarray(out).tobytes())
            else:  # models, reports, plots: pickle bytes (if these vary, downstream recomputes: the safe side)
                h.update(pickle.dumps(out, protocol=5))
    except (pickle.PicklingError, TypeError, AttributeError, ValueError):
        return None
    return h.hexdigest()[:16]
