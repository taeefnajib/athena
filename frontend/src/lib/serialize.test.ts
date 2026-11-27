import { describe, expect, it } from 'vitest'
import { fromPipelineSpec } from './serialize'
import { usePipelineStore } from '../store/pipelineStore'
import type { PipelineSpec } from '../types/pipeline'

const SPEC: PipelineSpec = {
  version: 1,
  name: 'untitled',
  nodes: [
    { id: 'n1', type: 'csv_loader', position: { x: 0, y: 0 }, config: { path: 'data.csv' } },
    { id: 'n2', type: 'db_connector', position: { x: 200, y: 0 }, config: { connection: 'wh' },
      timeout_s: 90, retry: { max_attempts: 3, backoff_s: 2 }, cache: false },
  ],
  edges: [{ id: 'e1', source: 'n1', target: 'n2', source_port: 0, target_port: 0 }],
}

describe('pipeline spec round trip (v2 execution policy)', () => {
  it('keeps per-node policy through load and save, and writes version 2', () => {
    const { nodes, edges } = fromPipelineSpec(SPEC)
    usePipelineStore.getState().loadPipeline(nodes, edges)
    const out = usePipelineStore.getState().toPipelineSpec()
    expect(out.version).toBe(2)
    expect(out.nodes[1]).toMatchObject({ timeout_s: 90, retry: { max_attempts: 3, backoff_s: 2 }, cache: false })
  })

  it('omits policy fields that are at their defaults', () => {
    const { nodes, edges } = fromPipelineSpec(SPEC)
    usePipelineStore.getState().loadPipeline(nodes, edges)
    const n1 = usePipelineStore.getState().toPipelineSpec().nodes[0]
    expect(Object.keys(n1).sort()).toEqual(['config', 'id', 'position', 'type'])
  })

  it('updateNodePolicy drops defaults (cache: true, empty retry)', () => {
    const { nodes, edges } = fromPipelineSpec(SPEC)
    const store = usePipelineStore.getState()
    store.loadPipeline(nodes, edges)
    store.updateNodePolicy('n2', { cache: true, retry: null, timeout_s: null })
    expect(usePipelineStore.getState().nodes[1].policy).toEqual({})
  })
})
