import { NODE_REGISTRY } from '../../registry/nodeRegistry'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { artifactUrl, TABLE_PORT_TYPES } from '../../lib/profile'

/** Port types whose outputs the backend can serialise for download (see GET /api/runs/{run}/artifacts). */
const DOWNLOADABLE = new Set([...TABLE_PORT_TYPES, 'model', 'report', 'transformer', 'pipeline'])

const btn: React.CSSProperties = {
  fontSize: 11, padding: '3px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)',
  color: 'var(--text)', cursor: 'pointer', textDecoration: 'none', whiteSpace: 'nowrap',
}

/** Profile / download each output of a node that finished in the current run. */
export function OutputActions({ nodeId, nodeType }: { nodeId: string; nodeType: string }) {
  const runId = useExecutionStore(s => s.runId)
  const status = useExecutionStore(s => s.nodeStates[nodeId]?.status)
  const setProfileTarget = useUiStore(s => s.setProfileTarget)
  const outputs = (NODE_REGISTRY[nodeType]?.outputs ?? []).map((p, i) => ({ ...p, i })).filter(p => DOWNLOADABLE.has(p.type))
  if (!runId || status !== 'success' || outputs.length === 0) return null
  return (
    <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 6 }}>
      {outputs.map(p => (
        <div key={p.i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
          {TABLE_PORT_TYPES.has(p.type) && (
            <button style={btn} onClick={() => setProfileTarget({ nodeId, port: p.i })} title="Statistics, data-quality findings and target association">Profile</button>
          )}
          <a style={btn} href={artifactUrl(runId, nodeId, p.i)} download title={TABLE_PORT_TYPES.has(p.type) ? 'Download as CSV' : 'Download'}>↓</a>
        </div>
      ))}
    </div>
  )
}
