"""Run observers: things that watch a run from inside the worker (experiment tracking, lineage, …).

A plugin registers a factory with ``register_observer_factory``. For every run the engine asks each
factory for an observer (``None`` = not interested, e.g. tracking is off for this pipeline). Observer
failures never fail the run: the engine reports them as a ``run_info`` warning and carries on.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    from athena.core.handler import HandlerResult
    from athena.schemas.pipeline import NodeSpec, PipelineSpec
    from athena.sdk.node import NodeMeta

Emit = Callable[[dict[str, Any]], None]


class RunObserver(Protocol):
    name: str

    def on_run_start(self, spec: PipelineSpec, run_id: str, emit: Emit) -> None: ...
    def on_node_finish(self, node: NodeSpec, meta: NodeMeta, result: HandlerResult) -> None: ...
    def on_run_finish(self, status: str) -> None: ...
    # Optional: def abandon(self, error: str) -> None, called when one of the hooks above raised.


ObserverFactory = Callable[["PipelineSpec"], "RunObserver | None"]
_FACTORIES: list[ObserverFactory] = []


def register_observer_factory(factory: ObserverFactory) -> None:
    if factory not in _FACTORIES:
        _FACTORIES.append(factory)


def build_observers(spec: PipelineSpec, emit: Emit) -> list[RunObserver]:
    out: list[RunObserver] = []
    for factory in _FACTORIES:
        try:
            obs = factory(spec)
        except Exception as exc:
            emit({"type": "run_info", "warning": f"{getattr(factory, '__name__', 'observer')}: {exc}"})
            continue
        if obs is not None:
            out.append(obs)
    return out


def notify(observers: list[RunObserver], emit: Emit, method: str, *args: Any) -> list[RunObserver]:
    """Call ``method`` on every observer; drop (and report) any that raise. Returns the survivors."""
    alive: list[RunObserver] = []
    for obs in observers:
        try:
            getattr(obs, method)(*args)
            alive.append(obs)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            emit({"type": "run_info", "warning": f"{obs.name} stopped: {message}"})
            abandon = getattr(obs, "abandon", None)
            if abandon is not None and method != "on_run_finish":
                try:
                    abandon(message)  # let it close whatever it opened (e.g. an MLflow run)
                except Exception:
                    pass
    return alive
