import time
import traceback

import anyio
import structlog

from athena.schemas.pipeline import PipelineSpec
from athena.schemas.events import NodeStart, NodeFinish, RunFinish, ErrorPayload
from athena.core.dag import topo_sort, is_descendant_of
from athena.core.handler import ExecutionContext, HandlerResult
from athena.core.registry import get_handler
from athena.core.events import EventBroker, broker as default_broker
from athena.core.cache import ArtifactCache, compute_cache_key
from athena.config import settings

logger = structlog.get_logger()

_active_run_id: str | None = None
_cancelled_runs: set[str] = set()


def get_active_run_id() -> str | None:
    return _active_run_id


def cancel_run(run_id: str) -> None:
    _cancelled_runs.add(run_id)


def is_cancelled(run_id: str) -> bool:
    return run_id in _cancelled_runs


def reset_active_run() -> None:
    """Clear leaked active-run state. Used by /api/runs/reset for recovery."""
    global _active_run_id
    _active_run_id = None
    _cancelled_runs.clear()


async def execute(
    spec: PipelineSpec,
    run_id: str,
    event_broker: EventBroker | None = None,
    start_from: list[str] | None = None,
) -> None:
    global _active_run_id
    _active_run_id = run_id
    if event_broker is None:
        event_broker = default_broker

    bound_log = logger.bind(run_id=run_id)

    try:
        await _run(spec, run_id, event_broker, start_from, bound_log)
    except Exception as exc:
        # Catch-all so the executor itself never silently swallows control flow
        # without notifying the client.
        bound_log.error("executor_crash", error=str(exc), tb=traceback.format_exc())
        try:
            await event_broker.publish(run_id, RunFinish(status="error"))
        except Exception:
            pass
    finally:
        _active_run_id = None
        _cancelled_runs.discard(run_id)


async def _run(
    spec: PipelineSpec,
    run_id: str,
    event_broker: EventBroker,
    start_from: list[str] | None,
    bound_log: structlog.BoundLogger,
) -> None:
    cache_dir = settings.data_dir / "cache" / run_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = ArtifactCache(cache_dir)

    nodes_dicts = [{"id": n.id} for n in spec.nodes]
    edges_dicts = [{"source": e.source, "target": e.target} for e in spec.edges]

    try:
        order = topo_sort(nodes_dicts, edges_dicts)
    except ValueError:
        await event_broker.publish(run_id, RunFinish(status="error"))
        return

    artifacts: dict[tuple[str, int], object] = {}
    node_cache_keys: dict[str, str] = {}

    for node_id in order:
        if is_cancelled(run_id):
            await event_broker.publish(run_id, RunFinish(status="cancelled"))
            return

        node = spec.node(node_id)

        if start_from and not is_descendant_of(node_id, start_from, edges_dicts) and node_id not in start_from:
            continue

        inputs: list[object] = []
        for e in spec.edges:
            if e.target == node_id:
                key = (e.source, e.source_port)
                if key in artifacts:
                    while len(inputs) <= e.target_port:
                        inputs.append(None)
                    inputs[e.target_port] = artifacts[key]

        parent_keys = [node_cache_keys.get(e.source, "") for e in spec.edges if e.target == node_id]
        cache_key = compute_cache_key(node.type, node.config, parent_keys)
        node_cache_keys[node_id] = cache_key

        await event_broker.publish(run_id, NodeStart(node_id=node_id))
        bound_log.info("node_start", node_id=node_id, node_type=node.type)

        start_time = time.monotonic()

        try:
            handler = get_handler(node.type)
        except KeyError:
            err = ErrorPayload(message=f"Unknown node type: {node.type!r}", traceback="")
            await event_broker.publish(run_id, NodeFinish(node_id=node_id, status="error", error=err))
            await event_broker.publish(run_id, RunFinish(status="error"))
            return

        cached = cache.get(cache_key)
        if cached is not None:
            result: HandlerResult = cached
            bound_log.info("cache_hit", node_id=node_id)
        else:
            node_log = bound_log.bind(node_id=node_id)
            ctx = ExecutionContext(
                node_id=node_id,
                node_type=node.type,
                config=dict(node.config),
                inputs=inputs,
                run_id=run_id,
                cache_dir=cache_dir,
                logger=node_log,
                _cancelled=lambda: is_cancelled(run_id),
            )

            try:
                result = await anyio.to_thread.run_sync(lambda: handler(ctx))  # type: ignore[arg-type]
                cache.set(cache_key, result)
            except Exception as exc:
                tb = traceback.format_exc()
                err = ErrorPayload(message=str(exc), traceback=tb)
                duration = int((time.monotonic() - start_time) * 1000)
                await event_broker.publish(run_id, NodeFinish(
                    node_id=node_id, status="error", duration_ms=duration, error=err,
                ))
                await event_broker.publish(run_id, RunFinish(status="error"))
                bound_log.error("node_error", node_id=node_id, error=str(exc))
                return

        for i, art in enumerate(result.outputs):
            artifacts[(node_id, i)] = art

        duration = int((time.monotonic() - start_time) * 1000)
        preview_data = result.preview.model_dump() if result.preview else None
        await event_broker.publish(run_id, NodeFinish(
            node_id=node_id, status="success",
            duration_ms=duration,
            preview=preview_data,
            metrics=result.metrics,
        ))
        bound_log.info("node_success", node_id=node_id, duration_ms=duration)

    await event_broker.publish(run_id, RunFinish(status="completed"))
    bound_log.info("run_completed", run_id=run_id)
