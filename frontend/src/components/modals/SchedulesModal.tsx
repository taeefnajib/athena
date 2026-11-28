import { useCallback, useEffect, useState } from 'react'
import { useUiStore } from '../../store/uiStore'

interface RunRecord {
  run_id: string; trigger: string; started: string; finished: string | null; status: string
  error: string | null; error_node: string | null; skipped: string[]
}
interface Schedule {
  name: string; pipeline: string; cron: string; enabled: boolean; next_run: string | null
  history: RunRecord[]; description: string; running_run: string | null
}
interface Preview { description: string; next: string[] }
interface LibraryFile { name: string; path: string }

const btn: React.CSSProperties = { fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }
const primary: React.CSSProperties = { ...btn, background: 'var(--accent)', borderColor: 'var(--accent)', color: 'white' }
const label: React.CSSProperties = { fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '16px 0 6px' }
const input: React.CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)' }
const mono: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 11.5 }

export const CRON_PRESETS: Array<[string, string]> = [
  ['Every hour', '0 * * * *'], ['Every day at 02:00', '0 2 * * *'], ['Weekdays at 08:00', '0 8 * * 1-5'],
  ['Every Monday at 06:00', '0 6 * * 1'], ['1st of the month', '0 3 1 * *'],
]

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.detail?.detail ?? `HTTP ${res.status}`)
  return body as T
}

/** "2026-11-29T02:00:00" -> "Sun 29 Nov, 02:00" (local time, as the scheduler uses). */
export function formatWhen(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

function duration(r: RunRecord): string {
  if (!r.finished) return ''
  const s = Math.round((new Date(r.finished).getTime() - new Date(r.started).getTime()) / 1000)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

const STATUS: Record<string, [string, string]> = {
  completed: ['✓', 'var(--success)'], error: ['✗', 'var(--error)'], cancelled: ['■', 'var(--text-muted)'], running: ['●', 'var(--running)'],
}

/** Schedules: run saved pipelines on a cron schedule while Athena is running; history of their runs; export to Airflow / Dagster. */
export function SchedulesModal() {
  const { setShowSchedulesModal, showToast } = useUiStore()
  const [items, setItems] = useState<Schedule[]>([])
  const [enabledGlobally, setEnabledGlobally] = useState(true)
  const [library, setLibrary] = useState<LibraryFile[]>([])
  const [selected, setSelected] = useState<string | null>(null)  // a schedule name, or null for "new"
  const [form, setForm] = useState({ name: '', pipeline: '', cron: '0 2 * * *', enabled: true })
  const [preview, setPreview] = useState<Preview | null>(null)
  const [cronError, setCronError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const res = await call<{ schedules: Schedule[]; scheduler_enabled: boolean }>('/api/schedules')
    setItems(res.schedules)
    setEnabledGlobally(res.scheduler_enabled)
    return res.schedules
  }, [])

  useEffect(() => {
    refresh().then(list => { if (list[0]) select(list[0]) }).catch(e => showToast(String(e), 'error'))
    call<{ files: LibraryFile[] }>('/api/pipelines/library').then(r => setLibrary(r.files)).catch(() => setLibrary([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // live: the scheduler starts runs on its own, so keep the list fresh (faster while a run is going)
  const anyRunning = items.some(s => s.running_run)
  useEffect(() => {
    const t = setInterval(() => { refresh().catch(() => undefined) }, anyRunning ? 2000 : 5000)
    return () => clearInterval(t)
  }, [anyRunning, refresh])

  // a new schedule starts from the most recently saved pipeline once the library has loaded
  useEffect(() => {
    if (selected === null && library[0]) setForm(f => (f.pipeline ? f : { ...f, pipeline: library[0].path }))
  }, [library, selected])

  useEffect(() => {
    const t = setTimeout(() => {
      call<Preview>(`/api/schedules/preview?cron=${encodeURIComponent(form.cron)}`)
        .then(p => { setPreview(p); setCronError(null) })
        .catch(e => { setPreview(null); setCronError(e instanceof Error ? e.message : String(e)) })
    }, 250)
    return () => clearTimeout(t)
  }, [form.cron])

  function select(s: Schedule | null) {
    setSelected(s?.name ?? null)
    setForm(s ? { name: s.name, pipeline: s.pipeline, cron: s.cron, enabled: s.enabled }
              : { name: '', pipeline: library[0]?.path ?? '', cron: '0 2 * * *', enabled: true })
  }

  const current = items.find(s => s.name === selected) ?? null

  const save = async () => {
    setBusy(true)
    try {
      const saved = await call<Schedule>('/api/schedules', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      await refresh()
      setSelected(saved.name)
      showToast(saved.enabled ? `Scheduled "${saved.name}": next run ${formatWhen(saved.next_run)}` : `Saved "${saved.name}" (paused)`, 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error')
    } finally { setBusy(false) }
  }

  const act = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn(); await refresh() } catch (e) { showToast(`${what}: ${e instanceof Error ? e.message : String(e)}`, 'error') } finally { setBusy(false) }
  }

  const close = () => setShowSchedulesModal(false)
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={close}>
      <div role="dialog" aria-label="Schedules" onClick={e => e.stopPropagation()}
           style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 'min(1000px, calc(100vw - 32px))', height: 'min(700px, calc(100vh - 48px))', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Schedules</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Run saved pipelines on a schedule while Athena is running, or export them to Airflow / Dagster</div>
          </div>
          <button onClick={close} aria-label="Close" style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          <div style={{ width: 240, borderRight: '1px solid var(--border)', padding: 14, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <button style={{ ...btn, marginBottom: 8, borderColor: selected === null ? 'var(--accent)' : 'var(--border)' }} onClick={() => select(null)}>+ New schedule</button>
            {items.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No schedules yet.</div>}
            {items.map(s => (
              <div key={s.name} role="button" onClick={() => select(s)}
                   style={{ padding: '8px 10px', borderRadius: 8, cursor: 'pointer', background: s.name === selected ? 'var(--card)' : 'transparent', border: `1px solid ${s.name === selected ? 'var(--border2)' : 'transparent'}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: 'var(--text)', fontWeight: 600 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: s.running_run ? 'var(--running)' : s.enabled ? 'var(--success)' : 'transparent', border: s.enabled || s.running_run ? 'none' : '1.5px solid var(--border2)' }} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                </div>
                <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginLeft: 13 }}>
                  {s.running_run ? 'running now' : s.enabled ? `next ${formatWhen(s.next_run)}` : 'paused'}
                </div>
              </div>
            ))}
          </div>
          <div style={{ flex: 1, padding: '6px 22px 20px', overflowY: 'auto' }}>
            {!enabledGlobally && (
              <div role="note" style={{ marginTop: 12, padding: '8px 12px', border: '1px solid var(--warning)', borderRadius: 8, fontSize: 12, color: 'var(--warning)' }}>
                The scheduler is off (ATHENA_SCHEDULER=false): schedules are kept but don't run. Run now still works.
              </div>
            )}
            <div style={label}>{current ? 'Schedule' : 'New schedule'}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: '8px 12px', alignItems: 'center', fontSize: 12, color: 'var(--text-dim)' }}>
              <span>Name</span>
              <input aria-label="Name" style={input} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Nightly retrain" />
              <span>Pipeline file</span>
              <div style={{ display: 'flex', gap: 6 }}>
                <input aria-label="Pipeline file" style={{ ...input, ...mono }} value={form.pipeline} onChange={e => setForm({ ...form, pipeline: e.target.value })} placeholder="C:\path\pipeline.athena" />
                {library.length > 0 && (
                  <select aria-label="Saved pipelines" style={{ ...input, width: 170 }} value="" onChange={e => e.target.value && setForm({ ...form, pipeline: e.target.value })}>
                    <option value="">Saved pipelines…</option>
                    {library.map(f => <option key={f.path} value={f.path}>{f.name}</option>)}
                  </select>
                )}
              </div>
              <span>Schedule (cron)</span>
              <div style={{ display: 'flex', gap: 6 }}>
                <input aria-label="Cron" style={{ ...input, ...mono, borderColor: cronError ? 'var(--error)' : 'var(--border)' }} value={form.cron} onChange={e => setForm({ ...form, cron: e.target.value })} />
                <select aria-label="Presets" style={{ ...input, width: 170 }} value="" onChange={e => e.target.value && setForm({ ...form, cron: e.target.value })}>
                  <option value="">Presets…</option>
                  {CRON_PRESETS.map(([l, c]) => <option key={c} value={c}>{l}</option>)}
                </select>
              </div>
              <span />
              <div style={{ fontSize: 11.5, color: cronError ? 'var(--error)' : 'var(--text-muted)' }}>
                {cronError ?? (preview ? `${preview.description} · next: ${preview.next.map(formatWhen).join(', ')}` : '…')}
              </div>
              <span>Active</span>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> run on this schedule
              </label>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
              <button style={primary} disabled={busy || !form.name.trim() || !form.pipeline.trim() || !!cronError} onClick={save}>{current ? 'Save changes' : 'Create schedule'}</button>
              {current && (
                <>
                  <button style={btn} disabled={busy || !!current.running_run} onClick={() => act('Run now', () => call(`/api/schedules/${encodeURIComponent(current.name)}/run`, { method: 'POST' }))}>Run now</button>
                  <a style={{ ...btn, textDecoration: 'none' }} href={`/api/schedules/${encodeURIComponent(current.name)}/export?target=airflow`} download>Export Airflow DAG</a>
                  <a style={{ ...btn, textDecoration: 'none' }} href={`/api/schedules/${encodeURIComponent(current.name)}/export?target=dagster`} download>Export Dagster job</a>
                  <button style={{ ...btn, marginLeft: 'auto', color: 'var(--error)' }} disabled={busy}
                          onClick={() => act('Delete', async () => { await call(`/api/schedules/${encodeURIComponent(current.name)}`, { method: 'DELETE' }); select(null) })}>Delete</button>
                </>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10, lineHeight: 1.6 }}>
              The saved file runs (not the canvas): save your changes to it for the next run to use them. Times are this computer's local time.
              Runs only happen while Athena is running; ones missed while it was closed aren't caught up, and a run never starts while another is going.
              To retrain only when data drifts, put a Quality Gate (rule <span style={mono}>dataset_drift == 1</span>, when a rule fails: <b>skip</b>) before training.
            </div>
            {current && (
              <>
                <div style={label}>Runs</div>
                {current.history.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No runs yet.</div>}
                {current.history.length > 0 && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
                        <th style={{ padding: '4px 6px', fontWeight: 600 }}>Started</th><th style={{ padding: '4px 6px', fontWeight: 600 }}>Trigger</th>
                        <th style={{ padding: '4px 6px', fontWeight: 600 }}>Result</th><th style={{ padding: '4px 6px', fontWeight: 600 }}>Took</th>
                      </tr>
                    </thead>
                    <tbody>
                      {current.history.map(r => {
                        const [icon, colour] = STATUS[r.status] ?? ['?', 'var(--text-muted)']
                        return (
                          <tr key={r.run_id} style={{ borderTop: '1px solid var(--border)', verticalAlign: 'top' }}>
                            <td style={{ padding: '6px', color: 'var(--text)', whiteSpace: 'nowrap' }}>{formatWhen(r.started)}</td>
                            <td style={{ padding: '6px', color: 'var(--text-dim)' }}>{r.trigger === 'manual' ? 'Run now' : 'Schedule'}</td>
                            <td style={{ padding: '6px', color: 'var(--text-dim)' }}>
                              <span style={{ color: colour, fontWeight: 600 }}>{icon} {r.status}</span>
                              {r.skipped.length > 0 && <span> · skipped after {r.skipped.join(', ')} (gate not met)</span>}
                              {r.error && <div style={{ color: 'var(--error)', marginTop: 2 }}>{r.error_node ? `${r.error_node}: ` : ''}{r.error}</div>}
                            </td>
                            <td style={{ padding: '6px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{duration(r)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
