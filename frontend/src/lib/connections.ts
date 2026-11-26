// Connectors (what Athena can talk to) and saved connections. Secrets are write-only from the
// browser's point of view: the backend stores them in the OS keychain and never sends them back.
import type { ConfigField } from '../registry/nodeRegistry'

export interface ConnectorSpec {
  type: string
  label: string
  category: string
  category_label: string
  description: string
  config: ConfigField[]
  secret_fields: string[]
  library: string
  license: string
  extras: Record<string, string>
}

export interface SavedConnection {
  name: string
  type: string
  label: string
  config: Record<string, unknown>
  /** Per secret field: whether one is saved, and the env:// reference if it is one (keychain values are never sent). */
  secrets: Record<string, { set: boolean; ref: string | null }>
  updated: string | null
  known_type: boolean
}

export interface TestResult { ok: boolean; message: string; details: Record<string, unknown> }

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.detail ?? `Request failed (${res.status})`)
  }
  return body as T
}

const json = (method: string, data: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
})

export const connectionsApi = {
  connectors: () => call<{ connectors: ConnectorSpec[] }>('/api/connectors').then(r => r.connectors),
  list: () => call<{ connections: SavedConnection[] }>('/api/connections').then(r => r.connections),
  save: (name: string, type: string, config: Record<string, unknown>) =>
    call<SavedConnection>('/api/connections', json('PUT', { name, type, config })),
  remove: (name: string) => call<{ ok: boolean }>(`/api/connections/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  test: (type: string, config: Record<string, unknown>, name?: string) =>
    call<TestResult>('/api/connections/test', json('POST', { type, config, name })),
}
