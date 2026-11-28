import { beforeAll, describe, expect, it } from 'vitest'
import { applyNodesResponse, type NodeSpec } from '../registry/nodeRegistry'
import type { PipelineEdge, PipelineNode } from '../store/pipelineStore'
import { groupNodes, innerIds, nodePorts, subflowConfig, ungroupNode, withFreshIds } from './subflow'

const spec = (type: string, inputs: string[], outputs: string[]): NodeSpec => ({
  type, label: type.toUpperCase(), category: 'data', description: '', config: [],
  inputs: inputs.map(t => ({ name: t, type: t })), outputs: outputs.map(t => ({ name: t, type: t })),
  exportable: true, export_note: null, available: true, unavailable_reason: null, runtime: 'python',
})

beforeAll(() => applyNodesResponse({ categories: [{ id: 'data', label: 'Data', icon: '' }], nodes: [
  spec('csv', [], ['dataset']), spec('imp', ['dataset'], ['dataset']), spec('sc', ['dataset'], ['dataset']),
  spec('split', ['dataset'], ['X_train', 'y_train']), spec('info', ['dataset'], ['dataset']),
] }))

const node = (id: string, type: string, x = 0, y = 0): PipelineNode => ({ id, type, position: { x, y }, config: { k: id }, status: 'idle' })
const edge = (id: string, source: string, target: string, sourcePort = 0, targetPort = 0): PipelineEdge => ({ id, source, target, sourcePort, targetPort })

// csv -> imp -> sc -> split ; sc -> info
const NODES = [node('csv', 'csv', 0, 0), node('imp', 'imp', 200, 40), node('sc', 'sc', 400, 80), node('split', 'split', 600, 0), node('info', 'info', 600, 200)]
const EDGES = [edge('a', 'csv', 'imp'), edge('b', 'imp', 'sc'), edge('c', 'sc', 'split'), edge('d', 'sc', 'info')]

describe('groupNodes', () => {
  // computed after beforeAll has loaded the registry (describe bodies run at collection time)
  let res: { nodes: PipelineNode[]; edges: PipelineEdge[] }
  let sf: ReturnType<typeof subflowConfig>
  beforeAll(() => {
    const r = groupNodes(NODES, EDGES, ['imp', 'sc'], 'sf1', 'Prep')
    if ('error' in r) throw new Error(r.error)
    res = r
    sf = subflowConfig(r.nodes.find(n => n.id === 'sf1')!.config)
  })

  it('builds ports from the edges crossing the selection', () => {
    expect(sf.inputs).toEqual([{ name: 'dataset', type: 'dataset', node: 'imp', port: 0 }])
    expect(sf.outputs).toEqual([{ name: 'dataset', type: 'dataset', node: 'sc', port: 0 }])  // one output feeding two nodes
    expect(sf.edges).toEqual([{ id: 'b', source: 'imp', target: 'sc', source_port: 0, target_port: 0 }])
    expect(nodePorts('subflow', res.nodes.find(n => n.id === 'sf1')!.config).outputs).toHaveLength(1)
  })

  it('rewires outside edges and keeps inner positions relative', () => {
    expect(res.nodes.map(n => n.id).sort()).toEqual(['csv', 'info', 'sf1', 'split'])
    expect(res.edges.map(e => `${e.source}:${e.sourcePort}>${e.target}:${e.targetPort}`).sort())
      .toEqual(['csv:0>sf1:0', 'sf1:0>info:0', 'sf1:0>split:0'])
    expect(res.nodes.find(n => n.id === 'sf1')!.position).toEqual({ x: 200, y: 40 })
    expect(sf.nodes.map(n => n.position)).toEqual([{ x: 0, y: 0 }, { x: 200, y: 40 }])
  })

  it('ungrouping restores the original graph', () => {
    const back = ungroupNode(res.nodes, res.edges, 'sf1')
    const key = (e: PipelineEdge) => `${e.source}:${e.sourcePort}>${e.target}:${e.targetPort}`
    expect(back.edges.map(key).sort()).toEqual(EDGES.map(key).sort())
    expect(back.nodes.map(n => [n.id, n.position.x, n.position.y]).sort()).toEqual(NODES.map(n => [n.id, n.position.x, n.position.y]).sort())
  })

  it('refuses a selection that would create a cycle, or a single node', () => {
    const r = groupNodes(NODES, EDGES, ['imp', 'split'], 'x')  // sc sits between them, outside the selection
    expect('error' in r && r.error).toMatch(/sits between/)
    expect('error' in groupNodes(NODES, EDGES, ['imp'], 'x')).toBe(true)
  })

  it('names duplicate ports after their node', () => {
    const r = groupNodes(NODES, [...EDGES], ['split', 'info'], 'g')
    if ('error' in r) throw new Error(r.error)
    expect(subflowConfig(r.nodes.find(n => n.id === 'g')!.config).inputs.map(p => p.name)).toEqual(['dataset (SPLIT)', 'dataset (INFO)'])
  })
})

describe('library helpers', () => {
  it('gives library subflows fresh inner ids and lists leaf ids for status', () => {
    const r = groupNodes(NODES, EDGES, ['imp', 'sc'], 'sf1')
    if ('error' in r) throw new Error(r.error)
    const cfg = subflowConfig(r.nodes.find(n => n.id === 'sf1')!.config)
    let i = 0
    const fresh = withFreshIds(cfg, () => `n_${++i}`)
    expect(fresh.nodes.map(n => n.id)).toEqual(['n_1', 'n_2'])
    expect(fresh.edges[0]).toMatchObject({ source: 'n_1', target: 'n_2' })
    expect([fresh.inputs[0].node, fresh.outputs[0].node]).toEqual(['n_1', 'n_2'])
    const nested = { ...cfg, nodes: [...cfg.nodes, { id: 'deep', type: 'subflow', position: { x: 0, y: 0 }, config: cfg as unknown as Record<string, unknown> }] }
    expect(innerIds('top', nested as unknown as Record<string, unknown>)).toEqual(['top.imp', 'top.sc', 'top.deep.imp', 'top.deep.sc'])
  })
})
