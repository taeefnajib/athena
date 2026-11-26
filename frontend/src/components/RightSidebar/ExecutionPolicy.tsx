import { useState } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import type { NodePolicy } from '../../types/pipeline'

const input: React.CSSProperties = {
  background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)',
  fontSize: 12, padding: '5px 8px', outline: 'none', fontFamily: 'var(--font)', width: '100%',
}
const label: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: 'var(--text-dim)' }
const hint: React.CSSProperties = { fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }

/** Per-node execution policy (workflow spec v2): timeout, retries, caching. */
export function ExecutionPolicy({ nodeId }: { nodeId: string }) {
  const policy = usePipelineStore(s => s.nodes.find(n => n.id === nodeId)?.policy) ?? {}
  const update = usePipelineStore(s => s.updateNodePolicy)
  const isSet = policy.timeout_s != null || policy.retry != null || policy.cache === false
  const [open, setOpen] = useState(isSet)
  const set = (patch: NodePolicy) => update(nodeId, { ...policy, ...patch })
  const attempts = policy.retry?.max_attempts ?? 1
  const backoff = policy.retry?.backoff_s ?? 0

  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '10px 16px 14px' }}>
      <div onClick={() => setOpen(!open)} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
        <span style={{ ...label, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>Execution</span>
        <span style={{ fontSize: 10, color: isSet ? 'var(--accent)' : 'var(--text-muted)' }}>{isSet ? 'custom' : 'defaults'} {open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={label}>Timeout (seconds)</label>
            <input style={input} type="number" min={1} placeholder="default (ATHENA_NODE_TIMEOUT_S)"
              value={policy.timeout_s ?? ''} onChange={e => set({ timeout_s: e.target.value === '' ? null : Math.max(1, Number(e.target.value)) })} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={label}>Attempts</label>
              <input style={input} type="number" min={1} max={10} value={attempts}
                onChange={e => {
                  const n = Math.min(10, Math.max(1, Number(e.target.value) || 1))
                  set({ retry: n === 1 && backoff === 0 ? null : { max_attempts: n, backoff_s: backoff } })
                }} />
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={label}>Backoff (s)</label>
              <input style={input} type="number" min={0} max={300} value={backoff} disabled={attempts === 1}
                onChange={e => set({ retry: { max_attempts: attempts, backoff_s: Math.min(300, Math.max(0, Number(e.target.value) || 0)) } })} />
            </div>
          </div>
          <div style={hint}>Retries re-run the node after an error, waiting the backoff (doubling each time). Timeouts and Stop are not retried.</div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}>
            <input type="checkbox" checked={policy.cache !== false} onChange={e => set({ cache: e.target.checked })} />
            Reuse cached result when inputs and settings are unchanged
          </label>
          {policy.cache === false && <div style={hint}>This node always re-runs (useful for nodes that read live data).</div>}
        </div>
      )}
    </div>
  )
}
