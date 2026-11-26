import { describe, expect, it } from 'vitest'
import { applyNodesResponse, categoryColor, CATEGORY_META, getNodeGroups, loadNodeRegistry, NODE_REGISTRY, type NodeSpec } from './nodeRegistry'
import { isValidConnection } from '../lib/validation'

const spec = (type: string, category: string, extra: Partial<NodeSpec> = {}): NodeSpec => ({
  type, label: type, category, description: '', inputs: [], outputs: [], config: [],
  exportable: true, export_note: null, available: true, unavailable_reason: null, runtime: 'python', ...extra,
})

const RESPONSE = {
  categories: [{ id: 'data', label: 'Data Input', icon: '⊞' }, { id: 'model', label: 'Models', icon: '◉' }],
  nodes: [
    spec('csv_loader', 'data', { outputs: [{ name: 'dataset', type: 'dataset' }] }),
    spec('imputer', 'data', { inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }] }),
    spec('rf', 'model', { inputs: [{ name: 'X_train', type: 'X_train' }], outputs: [{ name: 'model', type: 'model' }] }),
    spec('automl', 'model', { available: false, unavailable_reason: 'not yet' }),
    spec('my_plugin_node', 'llm'),
  ],
}

describe('node registry loaded from the backend', () => {
  it('fills NODE_REGISTRY and categories, including plugin categories', () => {
    applyNodesResponse(RESPONSE)
    expect(Object.keys(NODE_REGISTRY)).toHaveLength(5)
    expect(CATEGORY_META.data.color).toBe('var(--cat-data)')
    expect(CATEGORY_META.llm.color).toMatch(/^oklch/)
  })

  it('leaves unavailable nodes out of the library but keeps them loadable', () => {
    applyNodesResponse(RESPONSE)
    const groups = getNodeGroups()
    const model = groups.find(g => g.id === 'model')!
    expect(model.nodes.map(n => n.type)).toEqual(['rf'])
    expect(NODE_REGISTRY.automl).toBeDefined()
  })

  it('replaces, not merges, on reload', async () => {
    applyNodesResponse(RESPONSE)
    const fetchImpl = (async () => new Response(JSON.stringify({ categories: RESPONSE.categories, nodes: [RESPONSE.nodes[0]] }))) as unknown as typeof fetch
    await loadNodeRegistry(fetchImpl)
    expect(Object.keys(NODE_REGISTRY)).toEqual(['csv_loader'])
  })

  it('reports a failed request', async () => {
    const fetchImpl = (async () => new Response('nope', { status: 500 })) as unknown as typeof fetch
    await expect(loadNodeRegistry(fetchImpl)).rejects.toThrow('500')
  })

  it('gives plugin categories a stable colour', () => {
    expect(categoryColor('llm')).toBe(categoryColor('llm'))
  })
})

describe('connection validation uses the loaded specs', () => {
  it('accepts matching types and dataset-compatible split outputs', () => {
    applyNodesResponse(RESPONSE)
    expect(isValidConnection('csv_loader', 0, 'imputer', 0)).toBe(true)
  })

  it('rejects mismatched types and missing ports', () => {
    applyNodesResponse(RESPONSE)
    expect(isValidConnection('rf', 0, 'imputer', 0)).toBe(false) // model -> dataset
    expect(isValidConnection('csv_loader', 3, 'imputer', 0)).toBe(false)
    expect(isValidConnection('unknown', 0, 'imputer', 0)).toBe(false)
  })
})
