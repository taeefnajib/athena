import type { PipelineSpec } from '../types/pipeline'

const BASE = '/api'

class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown, message: string) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new ApiError(res.status, err, typeof err?.detail === 'string' ? err.detail : 'Request failed')
  }
  return res.json()
}

export { ApiError }

export const api = {
  runPipeline: (spec: PipelineSpec, opts?: { startFrom?: string[] }) =>
    request<{ run_id: string }>(`${BASE}/pipelines/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec, start_from: opts?.startFrom }),
    }),

  cancelRun: (runId: string) =>
    fetch(`${BASE}/runs/${runId}/cancel`, { method: 'POST' }),

  resetRuns: () =>
    fetch(`${BASE}/runs/reset`, { method: 'POST' }),

  uploadFile: async (file: File): Promise<{ path: string; name: string; size: string }> => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/files/upload`, { method: 'POST', body: fd })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
      throw new ApiError(res.status, err, typeof err?.detail === 'string' ? err.detail : 'Upload failed')
    }
    return res.json()
  },

  savePipeline: (path: string, spec: PipelineSpec) =>
    request<{ ok: boolean }>(`${BASE}/pipelines/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, spec }),
    }),

  loadPipeline: (path: string) =>
    request<{ spec: PipelineSpec }>(`${BASE}/pipelines/load`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  listPipelines: () =>
    request<{ files: Array<{ name: string; path: string; modified: number }> }>(`${BASE}/pipelines/library`),

  exportPipeline: async (spec: PipelineSpec, format: string): Promise<Blob> => {
    const res = await fetch(`${BASE}/pipelines/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec, format }),
    })
    if (!res.ok) throw await res.json()
    return res.blob()
  },

  autosave: (spec: PipelineSpec) =>
    fetch(`${BASE}/pipelines/autosave`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
    }),

  getLatestAutosave: async (): Promise<{ spec: PipelineSpec } | null> => {
    const res = await fetch(`${BASE}/pipelines/autosave/latest`)
    if (!res.ok) return null
    return res.json()
  },
}
