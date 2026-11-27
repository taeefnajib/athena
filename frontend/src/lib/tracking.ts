// Experiment tracking (MLflow) API: status, local store setup and run history.

export interface TrackingStatus {
  installed: boolean
  version: string | null
  install_hint: string
  local_store: string
  local_ready: boolean
}

export interface TrackedRun {
  run_id: string
  name: string
  status: string
  start_time: number | null
  duration_ms: number | null
  metrics: Record<string, number>
  params: Record<string, string>
  athena_run_id: string | null
  pipeline: string | null
  node_labels: string | null
}

export interface RunsResponse { runs: TrackedRun[]; destination: string; experiment_id: string | null; ui_url: string | null }

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = body?.detail
    throw new Error(typeof d === 'string' ? d : d?.detail ?? `Request failed (${res.status})`)
  }
  return body as T
}

export const trackingApi = {
  status: () => call<TrackingStatus>('/api/tracking/status'),
  initLocal: () => call<{ ok: boolean }>('/api/tracking/local/init', { method: 'POST' }),
  runs: (experiment: string, connection: string) =>
    call<RunsResponse>(`/api/tracking/runs?${new URLSearchParams({ experiment, connection, limit: '100' })}`),
}

/** Metrics where a smaller value is better (for highlighting the best run). */
export function lowerIsBetter(metric: string): boolean {
  return /(^|[._])(rmse|mse|mae|mape|smape|loss|error|log_loss|duration)/i.test(metric)
}

/** "n5.accuracy" -> "Metrics Node · accuracy", using the node labels the run recorded. */
export function metricLabel(key: string, labels: Record<string, string>): string {
  const dot = key.indexOf('.')
  if (dot < 0) return key
  const node = key.slice(0, dot)
  return `${labels[node] ?? node} · ${key.slice(dot + 1)}`
}

const QUALITY = ['accuracy', 'f1', 'roc_auc', 'pr_auc', 'precision', 'recall', 'r2', 'rmse', 'mae', 'mse', 'mape', 'smape', 'log_loss', 'silhouette']

/** Is this a model-quality metric (vs bookkeeping such as row counts)? */
export function isQualityMetric(key: string): boolean {
  return QUALITY.includes(key.slice(key.indexOf('.') + 1).toLowerCase())
}

/** Quality metrics first (in a sensible order), then everything else alphabetically. */
export function sortMetrics(keys: string[]): string[] {
  const rank = (k: string) => {
    const i = QUALITY.indexOf(k.slice(k.indexOf('.') + 1).toLowerCase())
    return i < 0 ? QUALITY.length : i
  }
  return [...keys].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}
