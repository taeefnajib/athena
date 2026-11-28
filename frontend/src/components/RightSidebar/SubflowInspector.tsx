import { useState, type ComponentType } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { innerNodes, subflowConfig } from '../../lib/subflow'
import { subflowStatus } from '../../nodes/SubflowNode'
import type { ArtifactPreview, LogEntry } from '../../types/pipeline'
import { RunFromHere } from './RunFromHere'
import { CodeTab } from './CodeTab'

const STATUS: Record<string, { color: string; label: string }> = {
  idle: { color: 'var(--text-muted)', label: 'Idle' }, running: { color: 'var(--running)', label: 'Running…' },
  success: { color: 'var(--success)', label: 'Complete' }, error: { color: 'var(--error)', label: 'Error' },
}
const btn: React.CSSProperties = { fontSize: 11, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }
const EMPTY: LogEntry[] = []

/** Inspector for a subflow node: its name, the nodes inside with their status (click one for its preview),
 *  Ungroup, Save to library, plus the inner nodes' logs and code. */
export function SubflowInspector({ nodeId, config, onRunFrom, Preview, Logs }: {
  nodeId: string
  config: Record<string, unknown>
  onRunFrom: (id: string) => void
  Preview: ComponentType<{ preview?: ArtifactPreview }>
  Logs: ComponentType<{ logs: LogEntry[] }>
}) {
  const sf = subflowConfig(config)
  const inner = innerNodes(nodeId, config)
  const { updateNodeConfig, ungroupNode } = usePipelineStore()
  const { showToast, bumpSubflowLibrary } = useUiStore()
  const states = useExecutionStore(s => s.nodeStates)
  const previews = useExecutionStore(s => s.previews)
  const allLogs = useExecutionStore(s => s.logs)
  const [tab, setTab] = useState<'nodes' | 'logs' | 'code'>('nodes')
  const [picked, setPicked] = useState<string | null>(null)
  const [name, setName] = useState(sf.name)
  const status = STATUS[subflowStatus(states, inner.map(n => n.id))]
  const logs = inner.flatMap(n => (allLogs[n.id] ?? EMPTY).map(l => ({ ...l, msg: `[${n.label}] ${l.msg}` })))

  const commitName = () => {
    const clean = name.trim() || 'Subflow'
    if (clean !== sf.name) updateNodeConfig(nodeId, { ...config, name: clean })
  }
  const save = async () => {
    try {
      const res = await fetch('/api/subflows', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config }) })
      const body = await res.json()
      if (!res.ok) throw new Error(body?.detail?.detail ?? `HTTP ${res.status}`)
      bumpSubflowLibrary()
      showToast(body.replaced ? `Updated "${sf.name}" in your subflows` : `Saved "${sf.name}" to your subflows (left sidebar)`, 'success')
    } catch (e) {
      showToast(`Couldn't save the subflow: ${e instanceof Error ? e.message : e}`, 'error')
    }
  }

  return (
    <div style={{ width: 280, minWidth: 280, background: 'var(--panel)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.04em', color: 'var(--text-muted)', marginBottom: 6 }}>SUBFLOW · {inner.length} NODES</div>
        <input value={name} onChange={e => setName(e.target.value)} onBlur={commitName} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
               aria-label="Subflow name"
               style={{ width: '100%', fontSize: 14, fontWeight: 700, color: 'var(--text)', background: 'transparent', border: '1px solid transparent', borderRadius: 6, padding: '2px 4px', marginLeft: -5, outline: 'none' }}
               onFocus={e => { e.currentTarget.style.borderColor = 'var(--border)' }} />
        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, margin: '4px 0 8px' }}>
          Runs as the nodes inside; {sf.inputs.length} input{sf.inputs.length === 1 ? '' : 's'}, {sf.outputs.length} output{sf.outputs.length === 1 ? '' : 's'}.
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: status.color }} />
          <span style={{ fontSize: 11, color: status.color }}>{status.label}</span>
          <RunFromHere nodeId={nodeId} onRunFrom={onRunFrom} />
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
          <button style={btn} onClick={save} title="Keep it in your subflow library to reuse in other pipelines">Save to library</button>
          <button style={btn} onClick={() => ungroupNode(nodeId)} title="Put the nodes back on the canvas to edit them (Ctrl+Z regroups)">Ungroup</button>
        </div>
      </div>
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        {(['nodes', 'logs', 'code'] as const).map(t => (
          <div key={t} onClick={() => setTab(t)} style={{ flex: 1, padding: '8px 4px', textAlign: 'center', fontSize: 11, cursor: 'pointer', textTransform: 'capitalize',
            fontWeight: tab === t ? 600 : 400, color: tab === t ? 'var(--accent)' : 'var(--text-muted)', borderBottom: tab === t ? '2px solid var(--accent)' : '2px solid transparent', marginBottom: -1 }}>{t}</div>
        ))}
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {tab === 'nodes' && (
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {inner.map(n => {
              const st = states[n.id]
              const s = STATUS[st?.status ?? 'idle']
              return (
                <button key={n.id} onClick={() => setPicked(picked === n.id ? null : n.id)}
                        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, border: 'none', cursor: 'pointer', textAlign: 'left',
                                 background: picked === n.id ? 'var(--card2)' : 'transparent', color: 'var(--text)' }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: st ? s.color : 'transparent', border: st ? 'none' : '1.5px solid var(--border2)' }} />
                  <span style={{ fontSize: 12, flex: 1 }}>{n.label}</span>
                  {st?.cached && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>cached</span>}
                  {st?.error && <span style={{ fontSize: 10, color: 'var(--error)' }}>error</span>}
                </button>
              )
            })}
            {picked && (
              <div style={{ marginTop: 8, borderTop: '1px solid var(--border)' }}>
                {states[picked]?.error && <div style={{ padding: '10px 4px 0', fontSize: 11, color: 'var(--error)' }}>{states[picked]?.error?.message}</div>}
                <Preview preview={previews[picked]} />
              </div>
            )}
            {!picked && <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>Click a node to see its preview. To change a node's settings, Ungroup, edit, then group again (Ctrl+G).</div>}
          </div>
        )}
        {tab === 'logs' && <Logs logs={logs} />}
        {tab === 'code' && <CodeTab nodeId={nodeId} />}
      </div>
    </div>
  )
}
