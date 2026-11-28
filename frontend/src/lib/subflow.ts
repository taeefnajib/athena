// Subflows: group nodes into one reusable node (backend: athena/core/subflows.py expands them before running).
// Pure functions over the pipeline's nodes and edges, so they're easy to test and to undo.
import type { PipelineEdge, PipelineNode } from '../store/pipelineStore'
import type { NodeSpec } from '../types/pipeline'
import { pickPolicy } from '../types/pipeline'
import { NODE_REGISTRY } from '../registry/nodeRegistry'
import { hasCycle } from './dag'

export const SUBFLOW = 'subflow'
export const SEP = '.'

export interface SubflowPort { name: string; type: string; node: string; port: number }
export interface SpecEdge { id: string; source: string; target: string; source_port: number; target_port: number }
export interface SubflowConfig {
  name: string
  description?: string
  nodes: NodeSpec[]
  edges: SpecEdge[]
  inputs: SubflowPort[]
  outputs: SubflowPort[]
}
export interface Port { name: string; type: string; optional?: boolean }

export function isSubflow(type: string): boolean { return type === SUBFLOW }

export function subflowConfig(config: Record<string, unknown>): SubflowConfig {
  return config as unknown as SubflowConfig
}

/** A node's ports: from the registry, or (for a subflow) from its config. */
export function nodePorts(type: string, config: Record<string, unknown>): { inputs: Port[]; outputs: Port[] } {
  if (isSubflow(type)) {
    const sf = subflowConfig(config)
    return { inputs: sf.inputs ?? [], outputs: sf.outputs ?? [] }
  }
  const spec = NODE_REGISTRY[type]
  return { inputs: spec?.inputs ?? [], outputs: spec?.outputs ?? [] }
}

/** Every leaf node id inside a subflow as the backend names them (``sf.inner``, nested subflows flattened). */
export function innerIds(id: string, config: Record<string, unknown>): string[] {
  return subflowConfig(config).nodes.flatMap(n =>
    isSubflow(n.type) ? innerIds(`${id}${SEP}${n.id}`, n.config) : [`${id}${SEP}${n.id}`])
}

/** Leaf nodes inside a subflow, as the backend runs them: full id, type and a readable label. */
export function innerNodes(id: string, config: Record<string, unknown>): Array<{ id: string; type: string; label: string }> {
  return subflowConfig(config).nodes.flatMap(n => isSubflow(n.type)
    ? innerNodes(`${id}${SEP}${n.id}`, n.config)
    : [{ id: `${id}${SEP}${n.id}`, type: n.type, label: NODE_REGISTRY[n.type]?.label ?? n.type }])
}

function uniqueNames(ports: Array<Omit<SubflowPort, 'name'> & { base: string; label: string }>): SubflowPort[] {
  const counts = new Map<string, number>()
  for (const p of ports) counts.set(p.base, (counts.get(p.base) ?? 0) + 1)
  return ports.map(({ base, label, ...rest }) => ({ ...rest, name: (counts.get(base) ?? 0) > 1 ? `${base} (${label})` : base }))
}

function label(n: PipelineNode): string {
  return isSubflow(n.type) ? subflowConfig(n.config).name : NODE_REGISTRY[n.type]?.label ?? n.type
}

export type GroupResult = { nodes: PipelineNode[]; edges: PipelineEdge[]; id: string } | { error: string }

/** Replace the selected nodes by one subflow node; edges crossing the selection become its ports. */
export function groupNodes(nodes: PipelineNode[], edges: PipelineEdge[], ids: string[], newId: string, name = 'Subflow'): GroupResult {
  const inside = new Set(ids)
  const members = nodes.filter(n => inside.has(n.id))
  if (members.length < 2) return { error: 'Select at least two nodes to group (Shift-click or drag a box)' }
  const minX = Math.min(...members.map(n => n.position.x)), minY = Math.min(...members.map(n => n.position.y))

  const incoming = edges.filter(e => !inside.has(e.source) && inside.has(e.target))
  const outgoing = edges.filter(e => inside.has(e.source) && !inside.has(e.target))
  const byId = new Map(nodes.map(n => [n.id, n]))
  const inKeys: string[] = [], outKeys: string[] = []
  for (const e of incoming) { const k = `${e.target}:${e.targetPort}`; if (!inKeys.includes(k)) inKeys.push(k) }
  for (const e of outgoing) { const k = `${e.source}:${e.sourcePort}`; if (!outKeys.includes(k)) outKeys.push(k) }
  const portOf = (key: string, side: 'inputs' | 'outputs') => {
    const [node, idx] = [key.slice(0, key.lastIndexOf(':')), Number(key.slice(key.lastIndexOf(':') + 1))]
    const n = byId.get(node) as PipelineNode
    const p = nodePorts(n.type, n.config)[side][idx]
    return { node, port: idx, type: p?.type ?? 'dataset', base: p?.name ?? `port ${idx}`, label: label(n) }
  }

  const config: SubflowConfig = {
    name,
    nodes: members.map(n => ({ id: n.id, type: n.type, position: { x: n.position.x - minX, y: n.position.y - minY },
                               config: n.config, ...pickPolicy(n.policy ?? {}) })),
    edges: edges.filter(e => inside.has(e.source) && inside.has(e.target))
      .map(e => ({ id: e.id, source: e.source, target: e.target, source_port: e.sourcePort, target_port: e.targetPort })),
    inputs: uniqueNames(inKeys.map(k => portOf(k, 'inputs'))),
    outputs: uniqueNames(outKeys.map(k => portOf(k, 'outputs'))),
  }
  const sub: PipelineNode = { id: newId, type: SUBFLOW, position: { x: minX, y: minY }, config: config as unknown as Record<string, unknown>, status: 'idle' }
  const rewired: PipelineEdge[] = edges.flatMap(e => {
    if (inside.has(e.source) && inside.has(e.target)) return []
    if (inside.has(e.target)) return [{ ...e, target: newId, targetPort: inKeys.indexOf(`${e.target}:${e.targetPort}`) }]
    if (inside.has(e.source)) return [{ ...e, source: newId, sourcePort: outKeys.indexOf(`${e.source}:${e.sourcePort}`) }]
    return [e]
  })
  const nextNodes = [...nodes.filter(n => !inside.has(n.id)), sub]
  if (hasCycle(nextNodes, rewired)) {
    return { error: 'These nodes can\'t be grouped: a node outside the selection sits between selected ones. Add it to the selection.' }
  }
  return { nodes: nextNodes, edges: rewired, id: newId }
}

/** Put a subflow's nodes back on the canvas (at the subflow's position) and reconnect its outside edges. */
export function ungroupNode(nodes: PipelineNode[], edges: PipelineEdge[], id: string): { nodes: PipelineNode[]; edges: PipelineEdge[] } {
  const sub = nodes.find(n => n.id === id)
  if (!sub || !isSubflow(sub.type)) return { nodes, edges }
  const sf = subflowConfig(sub.config)
  const restored: PipelineNode[] = sf.nodes.map(n => {
    const { id: nid, type, position, config, ...policy } = n
    return { id: nid, type, config, status: 'idle', position: { x: sub.position.x + position.x, y: sub.position.y + position.y },
             ...(Object.keys(policy).length ? { policy } : {}) }
  })
  const inner: PipelineEdge[] = sf.edges.map(e => ({ id: e.id, source: e.source, target: e.target, sourcePort: e.source_port, targetPort: e.target_port }))
  const outer: PipelineEdge[] = edges.flatMap(e => {
    if (e.target === id) { const p = sf.inputs[e.targetPort]; return p ? [{ ...e, target: p.node, targetPort: p.port }] : [] }
    if (e.source === id) { const p = sf.outputs[e.sourcePort]; return p ? [{ ...e, source: p.node, sourcePort: p.port }] : [] }
    return [e]
  })
  return { nodes: [...nodes.filter(n => n.id !== id), ...restored], edges: [...outer, ...inner] }
}

/** A library subflow with fresh inner ids, so ungrouping it never collides with nodes already on the canvas. */
export function withFreshIds(config: SubflowConfig, newId: () => string): SubflowConfig {
  const map = new Map(config.nodes.map(n => [n.id, newId()]))
  const re = (id: string) => map.get(id) ?? id
  return {
    ...config,
    nodes: config.nodes.map(n => ({ ...n, id: re(n.id) })),
    edges: config.edges.map(e => ({ ...e, id: `${re(e.source)}-${re(e.target)}-${e.source_port}-${e.target_port}`, source: re(e.source), target: re(e.target) })),
    inputs: config.inputs.map(p => ({ ...p, node: re(p.node) })),
    outputs: config.outputs.map(p => ({ ...p, node: re(p.node) })),
  }
}
