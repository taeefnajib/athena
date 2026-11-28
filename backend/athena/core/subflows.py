"""Subflows: a group of nodes saved as one reusable node.

A node of type ``subflow`` carries its inner nodes and edges in its config, plus the ports it exposes: each
input/output maps to a port of an inner node. Before running or exporting, ``expand`` replaces every subflow
by its inner nodes (ids ``<subflow>.<inner>``, nested subflows included) and rewires the edges that crossed
its boundary, so the engine, the cache, tracking and codegen only ever see ordinary nodes. Saved .athena files
keep subflows as they are.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from athena.schemas.pipeline import EdgeSpec, NodeSpec, PipelineSpec

SUBFLOW = "subflow"
SEP = "."
MAX_DEPTH = 8


class SubflowPort(BaseModel):
    name: str
    type: str
    node: str = Field(description="Inner node id")
    port: int = Field(ge=0, description="Port index on that inner node")


class SubflowConfig(BaseModel):
    name: str = "Subflow"
    description: str = ""
    nodes: list[NodeSpec]
    edges: list[EdgeSpec] = []
    inputs: list[SubflowPort] = []
    outputs: list[SubflowPort] = []

    def check(self, where: str) -> None:
        ids = {n.id for n in self.nodes}
        if not ids:
            raise ValueError(f"Subflow {where!r} has no nodes")
        for e in self.edges:
            if e.source not in ids or e.target not in ids:
                raise ValueError(f"Subflow {where!r}: edge {e.id!r} points outside the subflow")
        for kind, ports in (("input", self.inputs), ("output", self.outputs)):
            for p in ports:
                if p.node not in ids:
                    raise ValueError(f"Subflow {where!r}: {kind} {p.name!r} refers to a missing node {p.node!r}")


def _port(ports: list[SubflowPort], index: int, sub_id: str, kind: str) -> SubflowPort:
    if not 0 <= index < len(ports):
        raise ValueError(f"Subflow {sub_id!r} has no {kind} port {index}")
    return ports[index]


def expand(spec: PipelineSpec, start_from: list[str] | None = None, _depth: int = 0) -> tuple[PipelineSpec, list[str] | None]:
    """Replace subflow nodes by their contents. ``start_from`` ids that are subflows become all their inner nodes."""
    subs = {n.id: SubflowConfig.model_validate(n.config) for n in spec.nodes if n.type == SUBFLOW}
    if not subs:
        return spec, start_from
    if _depth >= MAX_DEPTH:
        raise ValueError(f"Subflows are nested more than {MAX_DEPTH} levels deep")
    for sid, sf in subs.items():
        sf.check(sid)

    def inner(sid: str, node_id: str) -> str:
        return f"{sid}{SEP}{node_id}"

    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []
    for n in spec.nodes:
        if n.id not in subs:
            nodes.append(n)
            continue
        sf = subs[n.id]
        nodes += [m.model_copy(update={"id": inner(n.id, m.id)}) for m in sf.nodes]
        edges += [e.model_copy(update={"id": inner(n.id, e.id), "source": inner(n.id, e.source), "target": inner(n.id, e.target)})
                  for e in sf.edges]
    for e in spec.edges:
        source, source_port, target, target_port = e.source, e.source_port, e.target, e.target_port
        if source in subs:
            out = _port(subs[source].outputs, source_port, source, "output")
            source, source_port = inner(source, out.node), out.port
        if target in subs:
            inp = _port(subs[target].inputs, target_port, target, "input")
            target, target_port = inner(target, inp.node), inp.port
        edges.append(e.model_copy(update={"source": source, "source_port": source_port, "target": target, "target_port": target_port}))

    start = None if start_from is None else [
        x for s in start_from for x in ([inner(s, m.id) for m in subs[s].nodes] if s in subs else [s])]
    return expand(spec.model_copy(update={"nodes": nodes, "edges": edges}), start, _depth + 1)  # nested subflows
