from pydantic import BaseModel, Field, model_validator
from typing import Any, Literal

SPEC_VERSION = 2


class NodePosition(BaseModel):
    x: float
    y: float


class RetryPolicy(BaseModel):
    max_attempts: int = Field(1, ge=1, le=10)
    """Total attempts, including the first. A node error is retried; cancellation and timeouts are not."""
    backoff_s: float = Field(0.0, ge=0, le=300)
    """Wait between attempts (doubles each time)."""


class Resources(BaseModel):
    """Requested resources. Advisory in local mode; enforced by distributed runtimes (roadmap phase 3)."""
    cpu: float | None = Field(None, gt=0)
    memory_gb: float | None = Field(None, gt=0)
    gpu: int | None = Field(None, ge=0)


class NodeSpec(BaseModel):
    id: str
    type: str
    position: NodePosition
    config: dict[str, Any] = {}
    # ---- v2: execution policy (all optional; omitted = defaults) ----
    runtime: str | None = None
    """Where the node runs. Only "python" (the local worker) exists today; None means the node's default."""
    timeout_s: int | None = Field(None, ge=1, le=86_400)
    """Overrides ATHENA_NODE_TIMEOUT_S for this node."""
    retry: RetryPolicy | None = None
    cache: bool = True
    """False: always re-run this node (e.g. it reads live data)."""
    resources: Resources | None = None


class EdgeSpec(BaseModel):
    id: str
    source: str
    target: str
    source_port: int = 0
    target_port: int = 0


class PipelineSpec(BaseModel):
    version: Literal[1, 2] = SPEC_VERSION
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    name: str = "untitled"
    # ---- v2 ----
    description: str = ""
    metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def _upgrade(self) -> "PipelineSpec":
        """v1 is a strict subset of v2: accept it and treat it as v2 from here on."""
        self.version = SPEC_VERSION
        return self

    def node(self, node_id: str) -> NodeSpec:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"Node {node_id} not found")


class RunRequest(BaseModel):
    spec: PipelineSpec
    start_from: list[str] | None = None


class SaveRequest(BaseModel):
    path: str
    spec: PipelineSpec


class LoadRequest(BaseModel):
    path: str


class ExportRequest(BaseModel):
    spec: PipelineSpec
    format: str  # "python" | "notebook" | "json" | "model"
