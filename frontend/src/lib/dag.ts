export function topoSort(nodes: { id: string }[], edges: { source: string; target: string }[]): string[] {
  const inDeg: Record<string, number> = {}
  nodes.forEach(n => { inDeg[n.id] = 0 })
  edges.forEach(e => { inDeg[e.target] = (inDeg[e.target] ?? 0) + 1 })
  const queue = nodes.filter(n => inDeg[n.id] === 0)
  const order: string[] = []
  while (queue.length > 0) {
    const node = queue.shift()!
    order.push(node.id)
    edges.filter(e => e.source === node.id).forEach(e => {
      inDeg[e.target]--
      if (inDeg[e.target] === 0) {
        const n = nodes.find(n => n.id === e.target)
        if (n) queue.push(n)
      }
    })
  }
  if (order.length !== nodes.length) throw new Error('Pipeline contains a cycle')
  return order
}

export function hasCycle(nodes: { id: string }[], edges: { source: string; target: string }[]): boolean {
  try { topoSort(nodes, edges); return false } catch { return true }
}

/** The node and everything downstream of it: what "Run from here" re-runs. */
export function withDescendants(id: string, edges: { source: string; target: string }[]): string[] {
  const seen = new Set([id])
  const stack = [id]
  while (stack.length) {
    const cur = stack.pop() as string
    for (const e of edges) if (e.source === cur && !seen.has(e.target)) { seen.add(e.target); stack.push(e.target) }
  }
  return [...seen]
}
