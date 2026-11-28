import { useEffect, useState } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import { useUiStore } from '../../store/uiStore'
import { api, type CodeSection } from '../../lib/api'
import { CodeEditor } from '../ui/LazyCodeEditor'

const btn: React.CSSProperties = { fontSize: 11, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }

/** The Python this node becomes in Export Code, regenerated as the pipeline changes (the backend's codegen). */
export function CodeTab({ nodeId }: { nodeId: string }) {
  const nodes = usePipelineStore(s => s.nodes)
  const edges = usePipelineStore(s => s.edges)
  const toPipelineSpec = usePipelineStore(s => s.toPipelineSpec)
  const showToast = useUiStore(s => s.showToast)
  const [data, setData] = useState<{ script: string; sections: CodeSection[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [full, setFull] = useState(false)

  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => {
      api.code(toPipelineSpec())
        .then(d => { if (alive) { setData(d); setError(null) } })
        .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
    }, 300)  // debounce: config edits and drags arrive in bursts
    return () => { alive = false; clearTimeout(timer) }
  }, [nodes, edges, toPipelineSpec])

  // A subflow's code is its inner nodes' sections (ids <subflow>.<inner>), in order.
  const parts = data?.sections.filter(s => s.node_id === nodeId || s.node_id.startsWith(`${nodeId}.`)) ?? []
  const section = parts.length ? {
    label: parts.length > 1 ? `${parts.length} nodes` : parts[0].label,
    exported: parts.every(p => p.exported),
    imports: [...new Set(parts.flatMap(p => p.imports))],
    code: parts.map(p => (parts.length > 1 ? `# --- ${p.label} (${p.node_id}) ---\n${p.code}` : p.code)).join('\n\n'),
  } : undefined
  const text = section ? [...section.imports, ...(section.imports.length ? [''] : []), section.code].join('\n') : ''
  const copy = (value: string) => navigator.clipboard.writeText(value).then(() => showToast('Copied to the clipboard', 'success'),
                                                                          () => showToast("Couldn't copy (clipboard blocked)", 'error'))

  return (
    <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
        What <strong style={{ color: 'var(--text-dim)' }}>Export Code</strong> writes for this node. Variable names follow its connections.
      </div>
      {error && <div style={{ fontSize: 11, color: 'var(--error)' }}>{error}</div>}
      {!data && !error && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Generating…</div>}
      {section && (
        <>
          {!section.exported && <div style={{ fontSize: 11, color: 'var(--warning)' }}>This node isn't exported yet (see the comment).</div>}
          <CodeEditor value={text} language="python" readOnly wrap={false} minHeight={60} maxHeight={520} ariaLabel={`Python code for ${section.label}`} />
          <div style={{ display: 'flex', gap: 6 }}>
            <button style={btn} onClick={() => copy(text)}>Copy</button>
            <button style={btn} onClick={() => setFull(true)}>Full script</button>
          </div>
        </>
      )}
      {full && data && (
        <div role="dialog" aria-label="Full exported script" onClick={() => setFull(false)}
             style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()}
               style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 'min(960px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ flex: 1, fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Exported script</div>
              <button style={btn} onClick={() => copy(data.script)}>Copy</button>
              <button onClick={() => setFull(false)} aria-label="Close" style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
            </div>
            <div style={{ padding: 14, overflow: 'auto' }}>
              <CodeEditor value={data.script} language="python" readOnly wrap={false} minHeight={300} maxHeight={10_000} ariaLabel="Full exported script" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
