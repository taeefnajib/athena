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

from pathlib import Path
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult
from athena.runtime import remote
from athena.schemas.pipeline import NodeSpec

_CONNECTED: str | None = None  # the address this process is connected to ("local" for a cluster it started)


def _joblib_on_ray() -> Any:
    import joblib
    from ray.util.joblib import register_ray
    register_ray()
    return joblib.parallel_backend("ray")  # n_jobs work inside the handler spreads over the cluster


def run_in_ray_task(node_type: str, config: dict[str, Any], inputs: list[Any], run_id: str, node_id: str,
                    cache_dir: str) -> remote.Outcome:
    """The Ray task's body (see runtime/remote.py)."""
    import socket
    return remote.execute(node_type, config, inputs, run_id, node_id, cache_dir, f"Ray worker {socket.gethostname()}", _joblib_on_ray)


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
    return remote.finish(ctx, ray.get(task.remote(ctx.node_type, ctx.config, ctx.inputs, ctx.run_id, ctx.node_id, str(ctx.cache_dir))))
