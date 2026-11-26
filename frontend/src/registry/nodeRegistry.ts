// Node specs come from the backend node SDK (GET /api/nodes): it is the single source of truth.
// This module only holds the types, the loaded registry, and presentation-only category styling.
// Never hand-add node entries here; define nodes with @node in the backend (see root CLAUDE.md §4.2).

interface FieldBase { id: string; label: string; help?: string }

export type ConfigField = FieldBase & (
  | { type: 'text'; default: string }
  | { type: 'number'; default: number; min?: number; max?: number; step?: number }
  | { type: 'select'; default: string; options: string[] }
  | { type: 'toggle'; default: boolean }
  | { type: 'textarea'; default: string; mono?: boolean }
  | { type: 'file'; default: string; accept?: string }
  | { type: 'hp_params'; default: Array<{ key: string; values: string }> }
  | { type: 'col_map'; default: Array<{ key: string; values: string }> }
  | { type: 'password'; default: string }
  /** A saved connection's name; `connector` limits the choices to one connector type. */
  | { type: 'connection'; default: string; connector?: string; empty_label?: string }
)

/** Port types are open strings: plugins can introduce new ones. Built-ins include dataset, X_train, model, … */
export type PortType = string
/** Categories are open strings: plugins can introduce new ones. */
export type NodeCategory = string

export interface PortSpec { name: string; type: PortType; optional?: boolean }

export interface NodeSpec {
  type: string
  label: string
  category: NodeCategory
  description: string
  inputs: PortSpec[]
  outputs: PortSpec[]
  config: ConfigField[]
  exportable: boolean
  export_note: string | null
  available: boolean
  unavailable_reason: string | null
  runtime: string
}

export interface CategoryMeta {
  label: string
  color: string
  icon: string
}

export interface NodeGroup extends CategoryMeta {
  id: NodeCategory
  nodes: NodeSpec[]
}

export interface NodesResponse {
  categories: Array<{ id: string; label: string; icon: string }>
  nodes: NodeSpec[]
}

/** Filled by loadNodeRegistry() before the app renders. */
export const NODE_REGISTRY: Record<string, NodeSpec> = {}
export const CATEGORY_META: Record<string, CategoryMeta> = {}

// Built-in categories have theme-aware colours in globals.css (--cat-<id>).
const THEMED_CATEGORIES = new Set([
  'data', 'quality', 'feature', 'balance', 'split', 'model',
  'advanced', 'ensemble', 'eval', 'interp', 'deploy', 'monitor',
])

/** A stable colour for categories added by plugins (no CSS variable). */
export function categoryColor(id: string): string {
  if (THEMED_CATEGORIES.has(id)) return `var(--cat-${id})`
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 360
  return `oklch(68% 0.18 ${h})`
}

/** Replace the registry with a /api/nodes response. */
export function applyNodesResponse(res: NodesResponse): void {
  for (const k of Object.keys(NODE_REGISTRY)) delete NODE_REGISTRY[k]
  for (const k of Object.keys(CATEGORY_META)) delete CATEGORY_META[k]
  for (const c of res.categories) CATEGORY_META[c.id] = { label: c.label, icon: c.icon, color: categoryColor(c.id) }
  for (const n of res.nodes) {
    NODE_REGISTRY[n.type] = n
    if (!CATEGORY_META[n.category]) {
      CATEGORY_META[n.category] = { label: n.category, icon: '●', color: categoryColor(n.category) }
    }
  }
}

export async function loadNodeRegistry(fetchImpl: typeof fetch = fetch): Promise<void> {
  const res = await fetchImpl('/api/nodes')
  if (!res.ok) throw new Error(`GET /api/nodes failed: ${res.status}`)
  applyNodesResponse(await res.json() as NodesResponse)
}

/** Library groups in category order. Unavailable (not yet implemented) nodes are left out. */
export function getNodeGroups(): NodeGroup[] {
  return Object.entries(CATEGORY_META)
    .map(([id, meta]) => ({
      id,
      ...meta,
      nodes: Object.values(NODE_REGISTRY).filter(n => n.category === id && n.available),
    }))
    .filter(g => g.nodes.length > 0)
}
