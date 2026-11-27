import { describe, expect, it } from 'vitest'
import { hasCycle, topoSort, withDescendants } from './dag'

const edges = [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }, { source: 'b', target: 'd' }, { source: 'a', target: 'e' }]
const nodes = ['a', 'b', 'c', 'd', 'e'].map(id => ({ id }))

describe('dag', () => {
  it('sorts topologically and detects cycles', () => {
    const order = topoSort(nodes, edges)
    expect(order.indexOf('a')).toBeLessThan(order.indexOf('b'))
    expect(order.indexOf('b')).toBeLessThan(order.indexOf('d'))
    expect(hasCycle(nodes, edges)).toBe(false)
    expect(hasCycle(nodes, [...edges, { source: 'd', target: 'a' }])).toBe(true)
  })

  it('withDescendants returns the node and everything downstream, not upstream or side branches', () => {
    expect(withDescendants('b', edges).sort()).toEqual(['b', 'c', 'd'])
    expect(withDescendants('c', edges)).toEqual(['c'])
  })
})
