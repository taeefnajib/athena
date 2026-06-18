export interface NodePosition { x: number; y: number }

export interface NodeSpec {
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
  version: 1
  nodes: NodeSpec[]
  edges: EdgeSpec[]
  name: string
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
