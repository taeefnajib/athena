import { useEffect, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { useConnectionStore } from '../../store/connectionStore'
import { trackingApi, type TrackingStatus } from '../../lib/tracking'
import { trackingOf, type TrackingSettings } from '../../types/pipeline'

const input: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '6px 10px', outline: 'none', fontFamily: 'var(--font)', width: '100%' }
const label: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: 'var(--text-dim)' }
const hint: React.CSSProperties = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = (primary = false): React.CSSProperties => ({ padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer', fontFamily: 'var(--font)', border: primary ? '1px solid transparent' : '1px solid var(--border)', background: primary ? 'var(--accent)' : 'var(--card)', color: primary ? 'white' : 'var(--text)' })

/** Pipeline-level experiment tracking settings (stored in spec.metadata.tracking). */
export function TrackingModal() {
  const { setShowTrackingModal, setShowConnectionsModal, showToast } = useUiStore()
  const { meta, setMeta } = usePipelineStore()
  const { connections, loaded, load } = useConnectionStore()
  const [status, setStatus] = useState<TrackingStatus | null>(null)
  const [draft, setDraft] = useState<TrackingSettings>(trackingOf(meta))
  const [name, setName] = useState(meta.name === 'untitled' ? '' : meta.name)
  const [initializing, setInitializing] = useState(false)

  useEffect(() => { trackingApi.status().then(setStatus).catch(e => showToast(e.message, 'error')) }, [showToast])
  useEffect(() => { if (!loaded) load().catch(() => {}) }, [loaded, load])

  const mlflowConnections = connections.filter(c => c.type === 'mlflow')
  const experiment = draft.experiment || name || 'untitled'

  const save = () => {
    setMeta({ name: name.trim() || 'untitled', metadata: { ...meta.metadata, tracking: draft } })
    showToast(draft.enabled ? `Runs will be tracked in experiment "${experiment}"` : 'Tracking turned off', 'success')
    setShowTrackingModal(false)
  }
  const initLocal = async () => {
    setInitializing(true)
    try { await trackingApi.initLocal(); setStatus(await trackingApi.status()); showToast('Local MLflow store ready', 'success') }
    catch (e) { showToast(e instanceof Error ? e.message : String(e), 'error') }
    finally { setInitializing(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowTrackingModal(false)}>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 480, boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Experiment tracking</div>
            <div style={{ ...hint, marginTop: 2 }}>Log every run of this pipeline to MLflow: settings, metrics, models and code.</div>
          </div>
          <button onClick={() => setShowTrackingModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>

        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {status && !status.installed && (
            <div style={{ ...hint, color: 'var(--warning)', border: '1px solid var(--warning)', borderRadius: 8, padding: '8px 10px' }}>{status.install_hint}</div>
          )}
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: 'var(--text)', cursor: 'pointer' }}>
            <input type="checkbox" checked={draft.enabled} disabled={!status?.installed} onChange={e => setDraft({ ...draft, enabled: e.target.checked })} />
            Track runs of this pipeline
          </label>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={label}>Pipeline name</label>
            <input style={input} value={name} placeholder="untitled" onChange={e => setName(e.target.value)} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={label}>Destination</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <select style={{ ...input, cursor: 'pointer' }} value={draft.connection} onChange={e => setDraft({ ...draft, connection: e.target.value })}>
                <option value="">Local MLflow store (~/.athena/mlflow)</option>
                {mlflowConnections.map(c => <option key={c.name} value={c.name}>{c.name} ({String(c.config.tracking_uri ?? '')})</option>)}
              </select>
              <button style={btn()} onClick={() => setShowConnectionsModal(true)}>Manage…</button>
            </div>
            {draft.connection === '' && status && (
              status.local_ready
                ? <div style={hint}>Stored at {status.local_store}</div>
                : <div style={{ ...hint, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>The local store is created on first use (one time, about 20 seconds).</span>
                    {status.installed && <button style={btn()} disabled={initializing} onClick={initLocal}>{initializing ? 'Setting up…' : 'Set up now'}</button>}
                  </div>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={label}>Experiment</label>
            <input style={input} value={draft.experiment} placeholder={name || 'pipeline name'} onChange={e => setDraft({ ...draft, experiment: e.target.value })} />
            <div style={hint}>Runs are grouped by experiment. Leave empty to use the pipeline name.</div>
          </div>

          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}>
            <input type="checkbox" checked={draft.log_models} onChange={e => setDraft({ ...draft, log_models: e.target.checked })} />
            Log trained models (so they can be registered later)
          </label>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}>
            <input type="checkbox" checked={draft.log_code} onChange={e => setDraft({ ...draft, log_code: e.target.checked })} />
            Log the pipeline's exported Python script with each run
          </label>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
            <button style={btn()} onClick={() => setShowTrackingModal(false)}>Cancel</button>
            <button style={btn(true)} onClick={save}>Save</button>
          </div>
        </div>
      </div>
    </div>
  )
}
