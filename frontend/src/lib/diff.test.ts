import { beforeAll, describe, expect, it } from 'vitest'
import { applyNodesResponse } from '../registry/nodeRegistry'
import type { PipelineSpec } from '../types/pipeline'
import { diffSpecs, showValue, stable } from './diff'

beforeAll(() => applyNodesResponse({ categories: [{ id: 'data', label: 'Data', icon: '' }], nodes: [
  { type: 'imputer', label: 'Missing Value Imputer', category: 'data', description: '', inputs: [], outputs: [],
    config: [{ id: 'strategy', label: 'Strategy', type: 'select', default: 'mean', options: ['mean', 'median'] }],
    exportable: true, export_note: null, available: true, unavailable_reason: null, runtime: 'python' },
] }))

const n = (id: string, type: string, config: Record<string, unknown> = {}, x = 0, extra: object = {}) =>
  ({ id, type, position: { x, y: 0 }, config, ...extra })
const e = (source: string, target: string, sp = 0, tp = 0) => ({ id: `${source}-${target}`, source, target, source_port: sp, target_port: tp })
const spec = (nodes: ReturnType<typeof n>[], edges: ReturnType<typeof e>[], extra: Partial<PipelineSpec> = {}): PipelineSpec =>
  ({ version: 2, name: 'p', nodes, edges, ...extra }) as PipelineSpec

describe('diffSpecs', () => {
  const base = spec([n('a', 'csv_loader', { path: 'x.csv' }), n('b', 'imputer', { strategy: 'mean' }), n('c', 'rf')], [e('a', 'b'), e('b', 'c')])

  it('finds added, removed, changed and moved nodes, and connection changes', () => {
    const current = spec([
      n('a', 'csv_loader', { path: 'x.csv' }, 200),                         // moved only
      n('b', 'imputer', { strategy: 'median' }, 0, { cache: false }),     // changed setting + policy
      n('d', 'xgb'),                                                       // added (c removed)
    ], [e('a', 'b'), e('b', 'd')], { name: 'p2' })
    const d = diffSpecs(base, current)
    expect(d.added.map(x => x.id)).toEqual(['d'])
    expect(d.removed.map(x => x.id)).toEqual(['c'])
    expect(d.moved).toEqual(['a'])
    expect(d.changed).toHaveLength(1)
    expect(d.changed[0].label).toBe('Missing Value Imputer')
    expect(d.changed[0].changes.map(c => [c.label, c.before, c.after])).toEqual([['Strategy', 'mean', 'median'], ['Cache', undefined, false]])
    expect(d.edgesAdded.map(x => x.key)).toEqual(['b:0>d:0'])
    expect(d.edgesRemoved.map(x => x.key)).toEqual(['b:0>c:0'])
    expect(d.pipeline.map(p => p.field)).toEqual(['name'])
    expect(d.empty).toBe(false)
  })

  it('treats equal content as unchanged regardless of key order or an explicit cache: true', () => {
    const same = spec([n('a', 'csv_loader', { path: 'x.csv' }), n('b', 'imputer', { strategy: 'mean' }, 0, { cache: true }), n('c', 'rf')],
                      [e('b', 'c'), e('a', 'b')])
    expect(diffSpecs(base, same).empty).toBe(true)
    expect(stable({ b: 1, a: [1, { d: 2, c: 3 }] })).toBe(stable({ a: [1, { c: 3, d: 2 }], b: 1 }))
  })

  it('summarises changes inside a subflow', () => {
    const sf = (strategy: string, name = 'Prep') => n('s', 'subflow', { name, nodes: [n('i', 'imputer', { strategy })], edges: [], inputs: [], outputs: [] })
    const d = diffSpecs(spec([sf('mean')], []), spec([sf('median', 'Clean')], []))
    expect(d.changed[0].changes.map(c => [c.label, c.after])).toEqual([['Name', 'Clean'], ['Nodes inside', '1 changed']])
  })

  it('renders values compactly', () => {
    expect(showValue(undefined)).toBe('(default)')
    expect(showValue('')).toBe('""')
    expect(showValue({ a: 1 })).toBe('{"a":1}')
    expect(showValue('x'.repeat(100))).toHaveLength(78)
  })
})
