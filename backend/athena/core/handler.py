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
