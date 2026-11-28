"""Run a node as a Ray task (runtime ``"ray"`` or ``"ray:<connection>"``).

The worker connects to Ray once per run: a local cluster it starts itself, or a saved ``ray`` connection's address.
The node's handler runs in a Ray worker with the node's resources (``cpu`` -> ``num_cpus``, ``gpu`` -> ``num_gpus``,
``memory_gb`` -> ``memory``), and joblib inside it uses Ray's backend, so ``n_jobs`` work (forests, grid and random
search, cross-validation) spreads over the cluster. Inputs and outputs travel through Ray's object store.

Log lines are collected in the Ray task and replayed when it returns (a node's logs arrive when it finishes).
For a remote cluster (``ray://``), Athena's own code can be shipped with the task (``py_modules``); the cluster
needs the libraries the node uses (scikit-learn, pandas, …), which ``pip`` in the connection can add.
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult
from athena.schemas.pipeline import NodeSpec

_CONNECTED: str | None = None  # the address this process is connected to ("local" for a cluster it started)


class RemoteNodeError(Exception):
    """A handler failed in its Ray task. ``str()`` is the handler's message; ``remote_traceback`` is where."""

    def __init__(self, message: str, remote_traceback: str) -> None:
        super().__init__(message)
        self.remote_traceback = remote_traceback


class _CapturingLogger:
    """The NodeLogger interface, recording (level, message) to replay in the worker."""

    def __init__(self, lines: list[tuple[str, str]], context: dict[str, Any] | None = None) -> None:
        self._lines, self._ctx = lines, dict(context or {})

    def bind(self, **kw: Any) -> _CapturingLogger:
        return _CapturingLogger(self._lines, {**self._ctx, **kw})

    def _log(self, level: str, event: str, kw: dict[str, Any]) -> None:
        detail = " ".join(f"{k}={v}" for k, v in {**self._ctx, **kw}.items())
        self._lines.append((level, f"{event} {detail}".strip()))

    def debug(self, event: str, **kw: Any) -> None: self._log("debug", event, kw)
    def info(self, event: str, **kw: Any) -> None: self._log("info", event, kw)
    def warning(self, event: str, **kw: Any) -> None: self._log("warning", event, kw)
    def warn(self, event: str, **kw: Any) -> None: self._log("warning", event, kw)
    def error(self, event: str, **kw: Any) -> None: self._log("error", event, kw)
    def exception(self, event: str, **kw: Any) -> None: self._log("error", event, kw)


def run_in_ray_task(node_type: str, config: dict[str, Any], inputs: list[Any], run_id: str, node_id: str,
                    cache_dir: str) -> tuple[HandlerResult | None, list[tuple[str, str]], tuple[str, str] | None]:
    """The Ray task's body: (result, log lines, (error message, traceback) or None)."""
    import socket

    from athena.plugins import load_plugins
    load_plugins()
    from athena.core.registry import get_handler
    lines: list[tuple[str, str]] = [("info", f"Running on Ray worker {socket.gethostname()}")]
    ctx = ExecutionContext(node_id=node_id, node_type=node_type, config=config, inputs=inputs, run_id=run_id,
                           cache_dir=Path(cache_dir), logger=_CapturingLogger(lines),  # type: ignore[arg-type]
                           _cancelled=lambda: False)
    try:
        import joblib
        from ray.util.joblib import register_ray
        register_ray()
        with joblib.parallel_backend("ray"):  # n_jobs work inside the handler spreads over the cluster
            return get_handler(node_type)(ctx), lines, None
    except Exception as exc:  # noqa: BLE001 - returned to the worker, which reports it like a local failure
        return None, lines, (str(exc) or type(exc).__name__, traceback.format_exc())


def _connect(connection: str) -> str:
    """Connect this worker process to Ray (once). Returns a description of where tasks run."""
    global _CONNECTED
    import ray
    target = connection or "local"
    if _CONNECTED is not None and ray.is_initialized():
        if _CONNECTED != target:
            raise RuntimeError(f"This run already uses Ray at {_CONNECTED}; one run can't use two Ray clusters")
        return target
    kwargs: dict[str, Any] = {"ignore_reinit_error": True, "log_to_driver": False}
    if connection:
        from athena.connectors.store import resolve_connection
        _, cfg = resolve_connection(connection)
        kwargs["address"] = cfg.address  # type: ignore[attr-defined]
        kwargs["namespace"] = cfg.namespace or None  # type: ignore[attr-defined]
        env: dict[str, Any] = {}
        if cfg.ship_athena:  # type: ignore[attr-defined]
            import athena
            env["py_modules"] = [str(Path(athena.__file__).parent)]
        pip = [p.strip() for p in cfg.pip.split(",") if p.strip()]  # type: ignore[attr-defined]
        if pip:
            env["pip"] = pip
        if env:
            kwargs["runtime_env"] = env
    else:
        kwargs["include_dashboard"] = False
    ray.init(**kwargs)
    _CONNECTED = target
    return target


def run(node: NodeSpec, ctx: ExecutionContext, connection: str) -> HandlerResult:
    import ray

    from athena.config import settings
    if ctx.node_type == "custom_code" and not settings.allow_custom_code:  # a remote cluster doesn't see our settings
        raise RuntimeError("Custom code is disabled (ATHENA_ALLOW_CUSTOM_CODE=false)")
    where = _connect(connection)
    res = node.resources
    options: dict[str, Any] = {"num_cpus": res.cpu if res and res.cpu else 1, "max_retries": 0}  # the engine retries
    if res and res.gpu:
        options["num_gpus"] = res.gpu
    if res and res.memory_gb:
        options["memory"] = int(res.memory_gb * 1024**3)
    asked = ", ".join(f"{k}={v:g}" for k, v in options.items() if k != "max_retries")
    ctx.logger.info(f"Submitting to Ray ({'local cluster' if where == 'local' else where}) with {asked}")
    total = ray.cluster_resources()
    if options.get("num_gpus", 0) > total.get("GPU", 0):
        raise RuntimeError(f"The node asks for {options['num_gpus']} GPU(s) but the Ray cluster has {total.get('GPU', 0):g}")
    task = ray.remote(**options)(run_in_ray_task)
    result, lines, error = ray.get(task.remote(ctx.node_type, ctx.config, ctx.inputs, ctx.run_id, ctx.node_id, str(ctx.cache_dir)))
    for level, msg in lines:
        getattr(ctx.logger, level)(msg)
    if error is not None:
        raise RemoteNodeError(*error)
    assert result is not None
    return result
