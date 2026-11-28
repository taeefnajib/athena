import { beforeEach, describe, expect, it } from 'vitest'
import { useExecutionStore } from './executionStore'
import { documentUrl } from '../lib/profile'

describe('executionStore.markFinished', () => {
  beforeEach(() => useExecutionStore.getState().reset())

  it('keeps the reports a node produced, and none for older events without the field', () => {
    const { markFinished } = useExecutionStore.getState()
    markFinished('drift', { node_id: 'drift', status: 'success', duration_ms: 5, documents: ['report.html'] })
    markFinished('csv', { node_id: 'csv', status: 'success', duration_ms: 1 })
    const states = useExecutionStore.getState().nodeStates
    expect(states.drift.documents).toEqual(['report.html'])
    expect(states.csv.documents).toEqual([])
  })
})

describe('documentUrl', () => {
  it('escapes ids and asks for a download when told to', () => {
    expect(documentUrl('r1', 'sf.drift', 'report.html')).toBe('/api/runs/r1/documents/sf.drift/report.html')
    expect(documentUrl('r1', 'a b', 'report.html', true)).toBe('/api/runs/r1/documents/a%20b/report.html?download=1')
  })
})
