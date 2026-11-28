import { NODE_REGISTRY } from '../../registry/nodeRegistry'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { artifactUrl, documentUrl, TABLE_PORT_TYPES } from '../../lib/profile'

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
  const setDeployTarget = useUiStore(s => s.setDeployTarget)
  const documents = useExecutionStore(s => s.nodeStates[nodeId]?.documents) ?? []
  const outputs = (NODE_REGISTRY[nodeType]?.outputs ?? []).map((p, i) => ({ ...p, i })).filter(p => DOWNLOADABLE.has(p.type))
  if (!runId || status !== 'success' || (outputs.length === 0 && documents.length === 0)) return null
  return (
    <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 6 }}>
      {documents.map(name => (
        <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)', flex: 1 }}>Full report ({name})</span>
          <a style={{ ...btn, borderColor: 'var(--accent)', color: 'var(--accent)' }} href={documentUrl(runId, nodeId, name)}
             target="_blank" rel="noopener noreferrer" title="Evidently's interactive report, in a new tab">Open report</a>
          <a style={btn} href={documentUrl(runId, nodeId, name, true)} download title="Download the HTML report">↓</a>
        </div>
      ))}
      {outputs.map(p => (
        <div key={p.i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
          {TABLE_PORT_TYPES.has(p.type) && (
            <button style={btn} onClick={() => setProfileTarget({ nodeId, port: p.i })} title="Statistics, data-quality findings and target association">Profile</button>
          )}
          {(p.type === 'model' || p.type === 'pipeline') && (
            <button style={btn} onClick={() => setDeployTarget({ nodeId, port: p.i })} title="Package it as a prediction service (local endpoint, Docker, BentoML)">Deploy</button>
          )}
          <a style={btn} href={artifactUrl(runId, nodeId, p.i)} download title={TABLE_PORT_TYPES.has(p.type) ? 'Download as CSV' : 'Download'}>↓</a>
        </div>
      ))}
    </div>
  )
}
