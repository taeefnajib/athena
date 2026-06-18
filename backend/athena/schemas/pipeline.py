from pydantic import BaseModel
from typing import Any


class NodePosition(BaseModel):
    x: float
    y: float


class NodeSpec(BaseModel):
    id: str
    type: str
    position: NodePosition
    config: dict[str, Any] = {}


class EdgeSpec(BaseModel):
    id: str
    source: str
    target: str
    source_port: int = 0
    target_port: int = 0


class PipelineSpec(BaseModel):
    version: int = 1
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    name: str = "untitled"

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
