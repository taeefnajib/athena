"""Running a node's handler away from the run's worker (a Ray task, a Kubernetes pod).

``execute`` is the body every remote runtime calls: it loads the nodes, runs the handler with a logger that records
lines (replayed by the worker when the result comes back) and returns ``(result, lines, error)`` instead of raising,
so the worker can report a remote failure exactly like a local one.
"""
from __future__ import annotations

import traceback
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult

Outcome = tuple["HandlerResult | None", list[tuple[str, str]], "tuple[str, str] | None"]


class RemoteNodeError(Exception):
    """A handler failed where it ran. ``str()`` is the handler's message; ``remote_traceback`` is where."""

    def __init__(self, message: str, remote_traceback: str) -> None:
        super().__init__(message)
        self.remote_traceback = remote_traceback


class CapturingLogger:
    """The NodeLogger interface, recording (level, message) to replay in the worker."""

    def __init__(self, lines: list[tuple[str, str]], context: dict[str, Any] | None = None,
                 sink: Callable[[str, str], None] | None = None) -> None:
        self._lines, self._ctx, self._sink = lines, dict(context or {}), sink

    def bind(self, **kw: Any) -> CapturingLogger:
        return CapturingLogger(self._lines, {**self._ctx, **kw}, self._sink)

    def _log(self, level: str, event: str, kw: dict[str, Any]) -> None:
        detail = " ".join(f"{k}={v}" for k, v in {**self._ctx, **kw}.items())
        line = (level, f"{event} {detail}".strip())
        self._lines.append(line)
        if self._sink is not None:  # as it happens (a runner streams these to the worker)
            self._sink(*line)

    def debug(self, event: str, **kw: Any) -> None: self._log("debug", event, kw)
    def info(self, event: str, **kw: Any) -> None: self._log("info", event, kw)
    def warning(self, event: str, **kw: Any) -> None: self._log("warning", event, kw)
    def warn(self, event: str, **kw: Any) -> None: self._log("warning", event, kw)
    def error(self, event: str, **kw: Any) -> None: self._log("error", event, kw)
    def exception(self, event: str, **kw: Any) -> None: self._log("error", event, kw)


def execute(node_type: str, config: dict[str, Any], inputs: list[Any], run_id: str, node_id: str, cache_dir: str,
            where: str, around: Callable[[], AbstractContextManager[Any]] = nullcontext,
            sink: Callable[[str, str], None] | None = None) -> Outcome:
    """Run one handler here. ``around`` wraps the call (e.g. joblib's Ray backend); ``sink`` receives each log line."""
    from athena.plugins import load_plugins
    load_plugins()
    from athena.core.registry import get_handler
    lines: list[tuple[str, str]] = []
    logger = CapturingLogger(lines, sink=sink)
    logger.info(f"Running on {where}")
    ctx = ExecutionContext(node_id=node_id, node_type=node_type, config=config, inputs=inputs, run_id=run_id,
                           cache_dir=Path(cache_dir), logger=logger,  # type: ignore[arg-type]
                           _cancelled=lambda: False)
    try:
        with around():
            return get_handler(node_type)(ctx), lines, None
    except Exception as exc:  # noqa: BLE001 - returned to the worker, which reports it like a local failure
        return None, lines, (str(exc) or type(exc).__name__, traceback.format_exc())


def finish(ctx: ExecutionContext, outcome: Outcome, already_shown: int = 0) -> HandlerResult:
    """In the worker: replay the remote log lines (after the first ``already_shown``, streamed earlier), then return
    the result or raise the remote error."""
    result, lines, error = outcome
    for level, msg in lines[already_shown:]:
        getattr(ctx.logger, level)(msg)
    if error is not None:
        raise RemoteNodeError(*error)
    assert result is not None
    return result
