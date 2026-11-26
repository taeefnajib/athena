export interface NodePosition { x: number; y: number }

/** Per-node execution policy (spec v2). Every field is optional; omitted means the default. */
export interface NodePolicy {
  runtime?: string | null
  timeout_s?: number | null
  retry?: { max_attempts: number; backoff_s: number } | null
  cache?: boolean
  resources?: { cpu?: number | null; memory_gb?: number | null; gpu?: number | null } | null
}

export interface NodeSpec extends NodePolicy {
  id: string
  type: string
  position: NodePosition
  config: Record<string, unknown>
}

export interface EdgeSpec {
  id: string
  source: string
  target: string
  source_port: number
  target_port: number
}

export interface PipelineSpec {
  /** The backend accepts 1 and 2 and always returns 2. */
  version: 1 | 2
  nodes: NodeSpec[]
  edges: EdgeSpec[]
  name: string
  description?: string
  metadata?: Record<string, unknown>
}

export const POLICY_KEYS = ['runtime', 'timeout_s', 'retry', 'cache', 'resources'] as const

/** The policy fields that are actually set (so files only carry what the user chose). */
export function pickPolicy(src: NodePolicy): NodePolicy {
  const out: NodePolicy = {}
  for (const k of POLICY_KEYS) {
    const v = src[k]
    if (v !== undefined && v !== null && !(k === 'cache' && v === true)) (out as Record<string, unknown>)[k] = v
  }
  return out
}

export type NodeStatus = 'idle' | 'running' | 'success' | 'error'

export interface ColumnInfo {
  name: string
  dtype: string
  missing: number
  missing_pct: number
  unique: number
  min?: number
  max?: number
  mean?: number
  median?: number
  std?: number
  top_values?: string[]
}

export interface ArtifactPreview {
  kind: 'dataframe' | 'metrics' | 'plot' | 'model' | 'text' | 'dataframe_info'
  // dataframe
  columns?: string[]
  rows?: unknown[][]
  shape?: [number, number]
  // metrics
  values?: Record<string, number>
  // plot
  format?: 'png_base64'
  data?: string
  // model
  summary?: string
  // text
  text?: string
  download_filename?: string
  download_content?: string
  // dataframe_info
  duplicates?: number
  total_missing?: number
  missing_pct?: number
  info_columns?: ColumnInfo[]
}

export interface LogEntry {
  level: 'debug' | 'info' | 'warn' | 'error' | 'success'
  msg: string
  ts: string
}

export interface NodeFinishEvent {
  node_id: string
  status: 'success' | 'error'
  duration_ms: number
  preview?: ArtifactPreview
  metrics?: Record<string, number>
  error?: { message: string; traceback: string }
}
