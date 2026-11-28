import { describe, expect, it } from 'vitest'
import { autoLayout, nodeSize } from './layout'

describe('autoLayout', () => {
  const nodes = [{ id: 'csv', ports: 1 }, { id: 'imp', ports: 1 }, { id: 'split', ports: 4 }, { id: 'rf', ports: 5 }, { id: 'm', ports: 3 }, { id: 'lone', ports: 1 }]
  const edges = [{ source: 'csv', target: 'imp' }, { source: 'imp', target: 'split' }, { source: 'split', target: 'rf' },
                 { source: 'rf', target: 'm' }, { source: 'split', target: 'm' }]
  const pos = autoLayout(nodes, edges)

  it('places every node, left to right along the edges, on the grid', () => {
    expect(Object.keys(pos).sort()).toEqual(nodes.map(n => n.id).sort())
    for (const e of edges) expect(pos[e.source].x).toBeLessThan(pos[e.target].x)
    for (const p of Object.values(pos)) { expect(p.x % 20).toBe(0); expect(p.y % 20).toBe(0) }
  })

  it('never overlaps nodes', () => {
    const boxes = nodes.map(n => ({ ...pos[n.id], ...nodeSize(n.ports) }))
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j]
      const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
      expect(overlap).toBe(false)
    }
  })

  it('ignores edges to unknown nodes and handles an empty graph', () => {
    expect(Object.keys(autoLayout([{ id: 'a', ports: 1 }], [{ source: 'a', target: 'ghost' }]))).toEqual(['a'])
    expect(autoLayout([], [])).toEqual({})
  })
})
