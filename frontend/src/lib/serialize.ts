import { pickPolicy, type PipelineSpec, type NodeStatus } from '../types/pipeline'
import type { PipelineNode, PipelineEdge } from '../store/pipelineStore'

export function fromPipelineSpec(spec: PipelineSpec): { nodes: PipelineNode[]; edges: PipelineEdge[] } {
  return {
    nodes: (spec.nodes ?? []).map(n => ({
      id: n.id,
      type: n.type,
      position: n.position ?? { x: 0, y: 0 },
      config: n.config ?? {},
      status: 'idle' as NodeStatus,
      policy: pickPolicy(n),
    })),
    edges: (spec.edges ?? []).map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourcePort: e.source_port ?? 0,
      targetPort: e.target_port ?? 0,
    })),
  }
}
