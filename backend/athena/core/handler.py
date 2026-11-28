from dataclasses import dataclass, field
from typing import Any, Callable
from pathlib import Path
import structlog

from athena.schemas.artifacts import ArtifactPreview


@dataclass
class PortSpec:
    name: str
    type: str


@dataclass
class ExecutionContext:
    node_id: str
    node_type: str
    config: dict[str, Any]
    inputs: list[Any]
    run_id: str
    cache_dir: Path
    logger: structlog.BoundLogger
    _cancelled: Callable[[], bool] = field(default=lambda: False)

    def cancelled(self) -> bool:
        return self._cancelled()


@dataclass
class HandlerResult:
    outputs: list[Any]
    preview: ArtifactPreview | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    replay: dict[str, Any] | None = None
    """What a preprocessing node learned, as a step ``athena/serving/replay_core.py`` can redo on new rows (so a
    deployed model takes raw data). ``{"kind": "skip"}`` marks training-only steps (row filters, balancing)."""
    documents: dict[str, str] = field(default_factory=dict)
    halt: str | None = None
    """Set by a node that decides the nodes after it shouldn't run (a Quality Gate with on_fail=skip): the engine
    skips all its descendants, without failing the run. The text says why (logged)."""
    """Full HTML reports by file name (e.g. Evidently's ``report.html``), too large for a preview: listed in
    ``node_finish.documents`` and served by ``GET /api/runs/{run}/documents/{node}/{name}``."""
