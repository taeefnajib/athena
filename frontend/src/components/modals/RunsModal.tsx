import { useCallback, useEffect, useMemo, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { isQualityMetric, lowerIsBetter, metricLabel, sortMetrics, trackingApi, type RunsResponse, type TrackedRun } from '../../lib/tracking'
import { trackingOf } from '../../types/pipeline'

const cell: React.CSSProperties = { padding: '6px 10px', borderBottom: '1px solid var(--border)', fontSize: 11.5, color: 'var(--text-dim)', whiteSpace: 'nowrap', fontFamily: 'var(--mono)' }
const head: React.CSSProperties = { ...cell, fontFamily: 'var(--font)', fontWeight: 600, color: 'var(--text-muted)', background: 'var(--card2)', position: 'sticky', top: 0, textAlign: 'left' }
const STATUS_COLOR: Record<string, string> = { FINISHED: 'var(--success)', FAILED: 'var(--error)', KILLED: 'var(--warning)', RUNNING: 'var(--running)' }

const fmt = (v: number | undefined) => v === undefined ? '–' : Math.abs(v) >= 1000 || Number.isInteger(v) ? String(v) : v.toFixed(4)
const when = (ms: number | null) => ms ? new Date(ms).toLocaleString() : '–'
const secs = (ms: number | null) => ms === null ? '–' : `${(ms / 1000).toFixed(1)} s`

function labelsOf(runs: TrackedRun[]): Record<string, string> {
  for (const r of runs) if (r.node_labels) { try { return JSON.parse(r.node_labels) } catch { /* ignore */ } }
  return {}
}

/** Run history of the pipeline's experiment, with side-by-side comparison. */
export function RunsModal() {
  const { setShowRunsModal, setShowTrackingModal } = useUiStore()
  const meta = usePipelineStore(s => s.meta)
  const lastRun = useExecutionStore(s => s.tracking?.run_id)
  const tracking = trackingOf(meta)
  const experiment = tracking.experiment || meta.name || 'untitled'
  const [data, setData] = useState<RunsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [onlyDiff, setOnlyDiff] = useState(true)

  const refresh = useCallback(() => {
    setError(null)
    trackingApi.runs(experiment, tracking.connection).then(setData).catch(e => setError(e.message))
  }, [experiment, tracking.connection])
  useEffect(refresh, [refresh])

  const runs = data?.runs ?? []
  const labels = useMemo(() => labelsOf(runs), [runs])
  const metricKeys = useMemo(() => sortMetrics([...new Set(runs.flatMap(r => Object.keys(r.metrics)))]), [runs])
  const shownMetrics = metricKeys.slice(0, 5)
  const compared = runs.filter(r => selected.includes(r.run_id))
  const toggle = (id: string) => setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowRunsModal(false)}>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 'min(1100px, 94vw)', height: 'min(680px, 90vh)', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Runs · {experiment}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {tracking.enabled ? data?.destination ?? '' : 'Tracking is off for this pipeline: showing earlier runs only.'}
            </div>
          </div>
          {data?.ui_url && <a href={data.ui_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: 'var(--accent)' }}>Open in MLflow ↗</a>}
          <button onClick={() => { setShowRunsModal(false); setShowTrackingModal(true) }} style={{ fontSize: 12, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }}>Tracking settings</button>
          <button onClick={refresh} style={{ fontSize: 12, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }}>Refresh</button>
          <button onClick={() => setShowRunsModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>

        <div style={{ flex: compared.length >= 2 ? '0 0 45%' : 1, overflow: 'auto' }}>
          {error && <div style={{ padding: 20, fontSize: 12, color: 'var(--error)' }}>{error}</div>}
          {!error && data && runs.length === 0 && (
            <div style={{ padding: 20, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.7 }}>
              No runs in “{experiment}” yet. {tracking.enabled ? 'Run the pipeline to log one.' : 'Turn on tracking under Tracking settings, then run the pipeline.'}
            </div>
          )}
          {runs.length > 0 && (
            <table style={{ borderCollapse: 'collapse', width: '100%', tableLayout: 'auto' }}>
              <thead><tr>
                <th style={head}></th><th style={head}>Started</th><th style={head}>Status</th><th style={head}>Duration</th>
                {shownMetrics.map(k => <th key={k} style={head} title={k}>{metricLabel(k, labels)}</th>)}
              </tr></thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.run_id} onClick={() => toggle(r.run_id)} style={{ cursor: 'pointer', background: selected.includes(r.run_id) ? 'var(--card)' : r.run_id === lastRun ? 'color-mix(in srgb, var(--accent) 8%, transparent)' : 'transparent' }}>
                    <td style={cell}><input type="checkbox" readOnly checked={selected.includes(r.run_id)} /></td>
                    <td style={{ ...cell, fontFamily: 'var(--font)', color: 'var(--text)' }}>{when(r.start_time)}{r.run_id === lastRun && <span style={{ color: 'var(--accent)', marginLeft: 6 }}>latest</span>}</td>
                    <td style={{ ...cell, color: STATUS_COLOR[r.status] ?? 'var(--text-dim)' }}>{r.status.toLowerCase()}</td>
                    <td style={cell}>{secs(r.duration_ms)}</td>
                    {shownMetrics.map(k => <td key={k} style={cell}>{fmt(r.metrics[k])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {compared.length >= 2 ? (
          <Comparison runs={compared} labels={labels} onlyDiff={onlyDiff} setOnlyDiff={setOnlyDiff} />
        ) : runs.length > 0 && (
          <div style={{ padding: '10px 20px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)' }}>Select two or more runs to compare them side by side.</div>
        )}
      </div>
    </div>
  )
}

function Comparison({ runs, labels, onlyDiff, setOnlyDiff }: { runs: TrackedRun[]; labels: Record<string, string>; onlyDiff: boolean; setOnlyDiff: (v: boolean) => void }) {
  const allMetrics = sortMetrics([...new Set(runs.flatMap(r => Object.keys(r.metrics)))])
  const paramKeys = [...new Set(runs.flatMap(r => Object.keys(r.params)))].sort()
  const paramDiffers = (k: string) => new Set(runs.map(r => r.params[k] ?? '')).size > 1
  const metricDiffers = (k: string) => new Set(runs.map(r => r.metrics[k])).size > 1
  const quality = allMetrics.filter(isQualityMetric)
  const other = allMetrics.filter(k => !isQualityMetric(k) && (!onlyDiff || metricDiffers(k)))
  const params = onlyDiff ? paramKeys.filter(paramDiffers) : paramKeys
  const best = (k: string) => {
    const vals = runs.map(r => r.metrics[k]).filter((v): v is number => v !== undefined)
    if (vals.length < 2 || new Set(vals).size < 2) return undefined  // a tie has no winner
    return lowerIsBetter(k) ? Math.min(...vals) : Math.max(...vals)
  }
  const section = (title: string) => (
    <tr><td colSpan={runs.length + 1} style={{ ...cell, fontFamily: 'var(--font)', fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)', background: 'var(--panel)' }}>{title}</td></tr>
  )
  const metricRow = (k: string) => {
    const b = best(k)
    return (
      <tr key={k}><td style={{ ...cell, fontFamily: 'var(--font)', color: 'var(--text)' }}>{metricLabel(k, labels)}</td>
        {runs.map(r => <td key={r.run_id} style={{ ...cell, color: b !== undefined && r.metrics[k] === b ? 'var(--success)' : cell.color, fontWeight: b !== undefined && r.metrics[k] === b ? 700 : 400 }}>{fmt(r.metrics[k])}</td>)}
      </tr>
    )
  }
  return (
    <div style={{ flex: 1, borderTop: '1px solid var(--border)', overflow: 'auto' }}>
      <div style={{ padding: '8px 20px', display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: 'var(--text-muted)' }}>
        <span style={{ fontWeight: 600, color: 'var(--text-dim)' }}>Comparing {runs.length} runs</span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={onlyDiff} onChange={e => setOnlyDiff(e.target.checked)} /> Only differences
        </label>
        <span>Best value in green; differing settings in amber.</span>
      </div>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead><tr><th style={head}></th>{runs.map(r => <th key={r.run_id} style={head}>{when(r.start_time)}</th>)}</tr></thead>
        <tbody>
          {quality.length > 0 && section('Model quality')}
          {quality.map(metricRow)}
          {section(onlyDiff ? 'Settings that differ' : 'Settings')}
          {params.map(k => (
            <tr key={k}><td style={{ ...cell, fontFamily: 'var(--font)' }}>{metricLabel(k, labels)}</td>
              {runs.map(r => <td key={r.run_id} style={{ ...cell, color: paramDiffers(k) ? 'var(--warning)' : cell.color, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.params[k]}>{r.params[k] ?? '–'}</td>)}
            </tr>
          ))}
          {params.length === 0 && <tr><td style={{ ...cell, fontFamily: 'var(--font)' }} colSpan={runs.length + 1}>No settings differ between these runs.</td></tr>}
          {other.length > 0 && section('Other metrics')}
          {other.map(metricRow)}
        </tbody>
      </table>
    </div>
  )
}
