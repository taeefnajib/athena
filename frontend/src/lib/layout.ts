import dagre from '@dagrejs/dagre'

export interface LayoutNode { id: string; ports: number }
export interface LayoutEdge { source: string; target: string }

/** BaseNode's rendered size: 200 px wide; header + one 26 px row per port. */
export function nodeSize(ports: number): { width: number; height: number } {
  return { width: 200, height: 42 + Math.max(1, ports) * 26 }
}

const GRID = 20

/** Left-to-right layered layout (dagre). Returns each node's top-left position, snapped to the canvas grid.
 *  Pure: callers decide when to apply it (only on an explicit "Tidy layout", never on its own). */
export function autoLayout(nodes: LayoutNode[], edges: LayoutEdge[]): Record<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90, marginx: 40, marginy: 40 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, nodeSize(n.ports))
  for (const e of edges) if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target)
  dagre.layout(g)
  const out: Record<string, { x: number; y: number }> = {}
  for (const n of nodes) {
    const p = g.node(n.id)
    const { width, height } = nodeSize(n.ports)
    out[n.id] = { x: Math.round((p.x - width / 2) / GRID) * GRID, y: Math.round((p.y - height / 2) / GRID) * GRID }
  }
  return out
}
