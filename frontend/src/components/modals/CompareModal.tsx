import { useEffect, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { api } from '../../lib/api'
import { diffSpecs, showValue, type NodeChange, type PipelineDiff } from '../../lib/diff'
import { nodePorts } from '../../lib/subflow'
import { NODE_REGISTRY } from '../../registry/nodeRegistry'
import type { PipelineSpec } from '../../types/pipeline'

interface LibraryFile { name: string; path: string; modified: number }

const section: React.CSSProperties = { fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '14px 0 6px' }
const btn: React.CSSProperties = { fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }
const tag = (text: string): JSX.Element => (
  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 99, border: '1px solid var(--border2)', color: 'var(--text-dim)', marginRight: 6 }}>{text}</span>
)

/** Compare the pipeline on the canvas with a saved version: what was added, removed or changed, field by field. */
export function CompareModal() {
  const { setShowCompareModal, setDiffMarks, showToast } = useUiStore()
  const toPipelineSpec = usePipelineStore(s => s.toPipelineSpec)
  const [library, setLibrary] = useState<LibraryFile[]>([])
  const [path, setPath] = useState('')
  const [against, setAgainst] = useState<string | null>(null)
  const [diff, setDiff] = useState<PipelineDiff | null>(null)
  const [specs, setSpecs] = useState<PipelineSpec[]>([])  // [saved, current]: to name the ends of changed connections
  const close = () => setShowCompareModal(false)

  useEffect(() => { api.listPipelines().then(r => setLibrary(r.files)).catch(() => setLibrary([])) }, [])

  const compare = async (target: string, label: string) => {
    try {
      const { spec } = await api.loadPipeline(target.trim())
      const current = toPipelineSpec()
      setDiff(diffSpecs(spec, current))  // the saved version is the "before"
      setSpecs([spec, current])
      setAgainst(label)
    } catch {
      showToast("Couldn't load that pipeline: check the path is an .athena file", 'error')
    }
  }
  const mark = () => {
    if (!diff || !against) return
    const marks: Record<string, 'added' | 'changed'> = {}
    for (const n of diff.added) marks[n.id] = 'added'
    for (const n of diff.changed) marks[n.id] = 'changed'
    setDiffMarks({ against, marks, removed: diff.removed.length })
    close()
  }

  /** "Random Forest · model" for one end of a connection, from whichever version has that node. */
  const end = (id: string, port: number, side: 'inputs' | 'outputs') => {
    const n = specs.map(s => s.nodes.find(x => x.id === id)).find(Boolean)
    if (!n) return id
    const label = n.type === 'subflow' ? String((n.config as { name?: string }).name ?? 'Subflow') : NODE_REGISTRY[n.type]?.label ?? n.type
    return `${label} · ${nodePorts(n.type, n.config)[side][port]?.name ?? `port ${port}`}`
  }

  const nodeRow = (n: NodeChange, kind: string) => (
    <div key={n.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ fontSize: 12, color: 'var(--text)' }}>{tag(kind)}<strong>{n.label}</strong> <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--mono)', fontSize: 10.5 }}>{n.id}</span></div>
      {n.changes.map(c => (
        <div key={c.field} style={{ fontSize: 11.5, color: 'var(--text-dim)', margin: '3px 0 0 8px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-muted)', minWidth: 110 }}>{c.label}</span>
          {c.before !== '' && <span style={{ fontFamily: 'var(--mono)', textDecoration: 'line-through', color: 'var(--text-muted)' }}>{showValue(c.before)}</span>}
          {c.before !== '' && <span style={{ color: 'var(--text-muted)' }}>→</span>}
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>{showValue(c.after)}</span>
        </div>
      ))}
    </div>
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={close}>
      <div role="dialog" aria-label="Compare versions" onClick={e => e.stopPropagation()}
           style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 'min(860px, calc(100vw - 32px))', height: 'min(640px, calc(100vh - 48px))', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Compare versions</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>What changed on the canvas since a saved version</div>
          </div>
          <button onClick={close} aria-label="Close" style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          <div style={{ width: 240, borderRight: '1px solid var(--border)', padding: 14, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Compare with</div>
            {library.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No saved pipelines yet.</div>}
            {library.map(f => (
              <button key={f.path} onClick={() => compare(f.path, f.name)} title={f.path}
                      style={{ textAlign: 'left', padding: '6px 8px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
                               background: against === f.name ? 'var(--card2)' : 'transparent', color: 'var(--text)' }}>
                {f.name}
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{new Date(f.modified * 1000).toLocaleString()}</div>
              </button>
            ))}
            <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '10px 0 4px' }}>or a file path</div>
            <input value={path} onChange={e => setPath(e.target.value)} placeholder="C:\path\pipeline.athena" onKeyDown={e => { if (e.key === 'Enter' && path.trim()) compare(path, path.trim()) }}
                   style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px', color: 'var(--text)', fontSize: 11.5, fontFamily: 'var(--mono)' }} />
            <button style={{ ...btn, marginTop: 4 }} disabled={!path.trim()} onClick={() => compare(path, path.trim())}>Compare</button>
          </div>
          <div style={{ flex: 1, padding: '6px 20px 16px', overflowY: 'auto' }}>
            {!diff && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 14 }}>Pick a saved version on the left.</div>}
            {diff && diff.empty && (
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 14 }}>
                No changes from <strong>{against}</strong>{diff.moved.length ? ` (${diff.moved.length} node${diff.moved.length > 1 ? 's' : ''} moved)` : ''}.
              </div>
            )}
            {diff && !diff.empty && (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
                  <div style={{ flex: 1, fontSize: 12.5, color: 'var(--text)' }}>
                    Since <strong>{against}</strong>: {diff.added.length} added · {diff.changed.length} changed · {diff.removed.length} removed
                    {diff.edgesAdded.length + diff.edgesRemoved.length > 0 && ` · ${diff.edgesAdded.length + diff.edgesRemoved.length} connection changes`}
                  </div>
                  <button style={btn} onClick={mark}>Show on canvas</button>
                </div>
                {diff.pipeline.length > 0 && <><div style={section}>Pipeline</div>{nodeRow({ id: '', type: '', label: 'Pipeline settings', changes: diff.pipeline }, 'changed')}</>}
                {diff.changed.length > 0 && <><div style={section}>Changed</div>{diff.changed.map(n => nodeRow(n, 'changed'))}</>}
                {diff.added.length > 0 && <><div style={section}>Added</div>{diff.added.map(n => nodeRow(n, 'new'))}</>}
                {diff.removed.length > 0 && <><div style={section}>Removed</div>{diff.removed.map(n => nodeRow(n, 'removed'))}</>}
                {(diff.edgesAdded.length > 0 || diff.edgesRemoved.length > 0) && (
                  <>
                    <div style={section}>Connections</div>
                    {[...diff.edgesAdded.map(e => ['+', e] as const), ...diff.edgesRemoved.map(e => ['−', e] as const)].map(([sign, e]) => (
                      <div key={sign + e.key} style={{ fontSize: 11.5, fontFamily: 'var(--mono)', color: 'var(--text-dim)', padding: '2px 0' }}>
                        {sign} {end(e.source, e.sourcePort, 'outputs')} → {end(e.target, e.targetPort, 'inputs')}
                      </div>
                    ))}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
