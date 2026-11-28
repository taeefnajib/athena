// What changed between two versions of a pipeline. Nodes are matched by id (ids are stable and never reused),
// so a node whose settings changed is "changed", not "removed + added".
import type { NodeSpec, PipelineSpec } from '../types/pipeline'
import { NODE_REGISTRY } from '../registry/nodeRegistry'

export interface FieldChange { field: string; label: string; before: unknown; after: unknown }
export interface NodeChange { id: string; type: string; label: string; changes: FieldChange[] }
export interface EdgeRef { key: string; source: string; target: string; sourcePort: number; targetPort: number }
export interface PipelineDiff {
  added: NodeChange[]
  removed: NodeChange[]
  changed: NodeChange[]
  moved: string[]
  edgesAdded: EdgeRef[]
  edgesRemoved: EdgeRef[]
  pipeline: FieldChange[]
  empty: boolean
}

const POLICY_LABELS: Record<string, string> = { timeout_s: 'Timeout (s)', retry: 'Retry', cache: 'Cache', runtime: 'Runtime', resources: 'Resources' }

/** JSON with sorted keys, so {a, b} and {b, a} compare equal. */
export function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(',')}]`
  if (v && typeof v === 'object') return `{${Object.keys(v as object).sort().map(k => `${JSON.stringify(k)}:${stable((v as Record<string, unknown>)[k])}`).join(',')}}`
  return JSON.stringify(v ?? null)
}

function nodeLabel(n: NodeSpec): string {
  return n.type === 'subflow' ? String((n.config as { name?: string }).name ?? 'Subflow') : NODE_REGISTRY[n.type]?.label ?? n.type
}

function fieldLabel(type: string, field: string): string {
  return NODE_REGISTRY[type]?.config.find(f => f.id === field)?.label ?? field
}

function edgeRefs(spec: { edges: PipelineSpec['edges'] }): Map<string, EdgeRef> {
  return new Map(spec.edges.map(e => {
    const key = `${e.source}:${e.source_port ?? 0}>${e.target}:${e.target_port ?? 0}`
    return [key, { key, source: e.source, target: e.target, sourcePort: e.source_port ?? 0, targetPort: e.target_port ?? 0 }]
  }))
}

function summary(d: PipelineDiff): string {
  const parts = [d.added.length && `${d.added.length} added`, d.removed.length && `${d.removed.length} removed`,
                 d.changed.length && `${d.changed.length} changed`, (d.edgesAdded.length + d.edgesRemoved.length) && 'connections changed']
  return parts.filter(Boolean).join(', ') || 'only moved'
}

function nodeChanges(before: NodeSpec, after: NodeSpec): FieldChange[] {
  const out: FieldChange[] = []
  if (before.type !== after.type) out.push({ field: 'type', label: 'Type', before: before.type, after: after.type })
  if (after.type === 'subflow' && before.type === 'subflow') {
    const b = before.config as unknown as PipelineSpec & { name?: string; inputs?: unknown; outputs?: unknown }
    const a = after.config as unknown as PipelineSpec & { name?: string; inputs?: unknown; outputs?: unknown }
    if (b.name !== a.name) out.push({ field: 'name', label: 'Name', before: b.name, after: a.name })
    const inner = diffSpecs({ ...b, name: '' } as PipelineSpec, { ...a, name: '' } as PipelineSpec)
    if (!inner.empty && (inner.added.length || inner.removed.length || inner.changed.length || inner.edgesAdded.length || inner.edgesRemoved.length)) {
      out.push({ field: 'nodes', label: 'Nodes inside', before: '', after: summary(inner) })
    }
    if (stable(b.inputs) !== stable(a.inputs) || stable(b.outputs) !== stable(a.outputs)) {
      out.push({ field: 'ports', label: 'Ports', before: '', after: 'changed' })
    }
  } else {
    const keys = [...new Set([...Object.keys(before.config ?? {}), ...Object.keys(after.config ?? {})])].sort()
    for (const k of keys) {
      const b = (before.config ?? {})[k], a = (after.config ?? {})[k]
      if (stable(b) !== stable(a)) out.push({ field: k, label: fieldLabel(after.type, k), before: b, after: a })
    }
  }
  for (const k of Object.keys(POLICY_LABELS)) {
    const b = (before as unknown as Record<string, unknown>)[k], a = (after as unknown as Record<string, unknown>)[k]
    const norm = (v: unknown) => (k === 'cache' ? v !== false : v ?? null)  // absent cache means true
    if (stable(norm(b)) !== stable(norm(a))) out.push({ field: k, label: POLICY_LABELS[k], before: b, after: a })
  }
  return out
}

/** ``base`` is the older version, ``current`` the newer. */
export function diffSpecs(base: PipelineSpec, current: PipelineSpec): PipelineDiff {
  const old = new Map(base.nodes.map(n => [n.id, n]))
  const now = new Map(current.nodes.map(n => [n.id, n]))
  const ref = (n: NodeSpec): NodeChange => ({ id: n.id, type: n.type, label: nodeLabel(n), changes: [] })
  const added = current.nodes.filter(n => !old.has(n.id)).map(ref)
  const removed = base.nodes.filter(n => !now.has(n.id)).map(ref)
  const changed: NodeChange[] = []
  const moved: string[] = []
  for (const n of current.nodes) {
    const o = old.get(n.id)
    if (!o) continue
    const changes = nodeChanges(o, n)
    if (changes.length) changed.push({ ...ref(n), changes })
    else if (o.position.x !== n.position.x || o.position.y !== n.position.y) moved.push(n.id)
  }
  const eb = edgeRefs(base), ec = edgeRefs(current)
  const edgesAdded = [...ec.values()].filter(e => !eb.has(e.key))
  const edgesRemoved = [...eb.values()].filter(e => !ec.has(e.key))
  const pipeline: FieldChange[] = []
  if ((base.name ?? '') !== (current.name ?? '')) pipeline.push({ field: 'name', label: 'Name', before: base.name, after: current.name })
  if ((base.description ?? '') !== (current.description ?? '')) pipeline.push({ field: 'description', label: 'Description', before: base.description, after: current.description })
  const tb = (base.metadata as { tracking?: unknown } | undefined)?.tracking, tc = (current.metadata as { tracking?: unknown } | undefined)?.tracking
  if (stable(tb) !== stable(tc)) pipeline.push({ field: 'tracking', label: 'Experiment tracking', before: tb, after: tc })
  const empty = !added.length && !removed.length && !changed.length && !edgesAdded.length && !edgesRemoved.length && !pipeline.length
  return { added, removed, changed, moved, edgesAdded, edgesRemoved, pipeline, empty }
}

/** A short, readable rendering of a config value for the diff list. */
export function showValue(v: unknown): string {
  if (v === undefined) return '(default)'
  if (typeof v === 'string') return v === '' ? '""' : v.length > 80 ? `${v.slice(0, 77)}…` : v
  const s = JSON.stringify(v)
  return s.length > 80 ? `${s.slice(0, 77)}…` : s
}
