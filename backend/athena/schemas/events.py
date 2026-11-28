from pydantic import BaseModel, Field
from typing import Literal, Any
from datetime import datetime, timezone


class NodeStart(BaseModel):
    type: Literal["node_start"] = "node_start"
    node_id: str


class NodeLog(BaseModel):
    type: Literal["node_log"] = "node_log"
    node_id: str
    level: Literal["debug", "info", "warn", "error"]
    msg: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ErrorPayload(BaseModel):
    message: str
    traceback: str = ""


class NodeFinish(BaseModel):
    type: Literal["node_finish"] = "node_finish"
    node_id: str
    status: Literal["success", "error"]
    duration_ms: int = 0
    preview: Any | None = None
    metrics: dict[str, float] = {}
    error: ErrorPayload | None = None
    cached: bool = False
    """True when the node's result was reused from an earlier run instead of recomputed."""
    documents: list[str] = []
    halted: bool = False
    """True when the node chose to skip everything after it (Quality Gate with on_fail=skip); those nodes don't run."""
    """Names of the HTML reports the node produced (fetched separately; see GET /api/runs/{run}/documents)."""


class RunFinish(BaseModel):
    type: Literal["run_finish"] = "run_finish"
    status: Literal["completed", "error", "cancelled"]


class RunInfo(BaseModel):
    """Run-level information from observers: tracking details, progress messages or warnings."""
    type: Literal["run_info"] = "run_info"
    tracking: dict[str, Any] | None = None
    message: str | None = None
    warning: str | None = None


RunEvent = NodeStart | NodeLog | NodeFinish | RunFinish | RunInfo
