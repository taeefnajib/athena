// Dataset profiles and downloads of node outputs from a finished run (backend: athena/profiling.py, api/runs.py).

export interface Histogram { edges: Array<number | null>; counts: number[] }
export interface TopValue { value: string; count: number }

export interface ColumnProfile {
  name: string
  dtype: string
  kind: 'numeric' | 'binary' | 'categorical' | 'text' | 'datetime' | 'empty'
  missing: number
  missing_pct: number
  unique: number
  unique_pct: number
  min?: number | string | null
  max?: number | string | null
  mean?: number | null
  median?: number | null
  std?: number | null
  skew?: number | null
  histogram?: Histogram
  top?: TopValue[]
  other_count?: number
}

export interface Insight { severity: 'warning' | 'info'; code: string; column: string | null; message: string }

export interface TargetSummary {
  name: string
  task: 'classification' | 'regression'
  classes?: Array<{ value: string; count: number; pct: number }>
  histogram?: Histogram
  mean?: number | null
}

export interface Profile {
  overview: {
    rows: number; columns: number; profiled_rows: number; sampled: boolean
    duplicate_rows: number; missing_cells: number; missing_pct: number; memory_mb: number
    kinds: Record<string, number>
  }
  columns: ColumnProfile[]
  insights: Insight[]
  target: TargetSummary | null
  association: Array<{ column: string; score: number | null }>
}

/** Output port types that hold a table (or a column) and can be profiled or downloaded as CSV. */
export const TABLE_PORT_TYPES = new Set(['dataset', 'X_train', 'X_test', 'X_val', 'y_train', 'y_test', 'y_val', 'predictions', 'outliers'])

export async function fetchProfile(runId: string, nodeId: string, port: number, target = ''): Promise<Profile> {
  const qs = target ? `?${new URLSearchParams({ target })}` : ''
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/profile/${encodeURIComponent(nodeId)}/${port}${qs}`)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.detail?.detail ?? `Profiling failed (${res.status})`)
  return body as Profile
}

export function artifactUrl(runId: string, nodeId: string, port: number, format: 'csv' | 'parquet' = 'csv'): string {
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(nodeId)}/${port}?format=${format}`
}

/** 1284 -> "1,284", 12900 -> "12.9K" */
export function compact(n: number): string {
  if (Math.abs(n) < 10_000) return n.toLocaleString()
  const units: Array<[number, string]> = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]
  for (const [v, s] of units) if (Math.abs(n) >= v) return `${(n / v).toFixed(1).replace(/\.0$/, '')}${s}`
  return String(n)
}

export function fmtNum(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return '–'
  if (typeof v === 'string') return v
  if (Number.isInteger(v)) return compact(v)
  const a = Math.abs(v)
  return a >= 1000 ? compact(Math.round(v)) : a >= 1 ? v.toFixed(2) : v.toPrecision(3)
}
