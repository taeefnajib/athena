import { useRef, useState, useEffect } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { api } from '../../lib/api'
import type { PipelineSpec } from '../../types/pipeline'

const inputStyle: React.CSSProperties = {
  background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '8px 10px', color: 'var(--text)', fontSize: 13, outline: 'none',
  fontFamily: 'var(--mono)', width: '100%', boxSizing: 'border-box',
}

interface LibraryFile { name: string; path: string; modified: number }

export function LoadModal() {
  const { setShowLoadModal, showToast } = useUiStore()
  const loadPipeline = usePipelineStore(s => s.loadPipeline)
  const [path, setPath] = useState('')
  const [loading, setLoading] = useState(false)
  const [library, setLibrary] = useState<LibraryFile[]>([])
  const [libraryLoading, setLibraryLoading] = useState(true)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.listPipelines()
      .then(res => setLibrary(res.files))
      .catch(() => setLibrary([]))
      .finally(() => setLibraryLoading(false))
  }, [])

  const applySpec = (spec: PipelineSpec) => {
    loadPipeline(
      spec.nodes.map(n => ({ id: n.id, type: n.type, position: n.position, config: n.config, status: 'idle' as const })),
      spec.edges.map(e => ({ id: e.id, source: e.source, target: e.target, sourcePort: e.source_port, targetPort: e.target_port })),
    )
    showToast('Pipeline loaded', 'success')
    setShowLoadModal(false)
  }

  const onLoadFromPath = async (loadPath?: string) => {
    const target = (loadPath ?? path).trim()
    if (!target) return
    setLoading(true)
    try {
      const res = await api.loadPipeline(target)
      applySpec(res.spec)
    } catch {
      showToast('Load failed — check the path exists and is a valid .athena file', 'error')
    } finally {
      setLoading(false)
    }
  }

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const spec = JSON.parse(text) as PipelineSpec
      if (!spec.nodes || !spec.edges) throw new Error('Missing nodes or edges')
      applySpec(spec)
    } catch {
      showToast('Invalid .athena file — could not parse pipeline', 'error')
    }
    e.target.value = ''
  }

  const fmtDate = (ts: number) => new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={() => setShowLoadModal(false)}
    >
      <div
        style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 480, maxHeight: '80vh', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ padding: '18px 20px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Load Pipeline</div>
          <button onClick={() => setShowLoadModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>×</button>
        </div>

        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
          {/* Library */}
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', display: 'block', marginBottom: 8, letterSpacing: '0.02em' }}>
              SAVED PIPELINES
            </label>
            {libraryLoading ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '10px 0' }}>Loading…</div>
            ) : library.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '10px 0' }}>No saved pipelines yet — save one first.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
                {library.map(f => (
                  <button
                    key={f.path}
                    onClick={() => onLoadFromPath(f.path)}
                    disabled={loading}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '8px 12px', borderRadius: 7, border: '1px solid var(--border)',
                      background: 'var(--card)', cursor: loading ? 'not-allowed' : 'pointer',
                      textAlign: 'left', transition: 'border-color 0.12s',
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>{f.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{fmtDate(f.modified)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>or load from file / path</span>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
          </div>

          {/* File upload */}
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', display: 'block', marginBottom: 8, letterSpacing: '0.02em' }}>
              UPLOAD FROM COMPUTER
            </label>
            <input
              ref={fileRef}
              type="file"
              accept=".athena,application/json"
              style={{ display: 'none' }}
              onChange={onFileChange}
            />
            <button
              onClick={() => fileRef.current?.click()}
              style={{
                width: '100%', padding: '12px', borderRadius: 8,
                border: '1.5px dashed var(--border2)', background: 'var(--card)',
                color: 'var(--text-dim)', cursor: 'pointer', fontSize: 12, fontWeight: 500,
              }}
            >
              Choose .athena file…
            </button>
          </div>

          {/* Path input */}
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', display: 'block', marginBottom: 6, letterSpacing: '0.02em' }}>
              FILE PATH
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                style={{ ...inputStyle, flex: 1 }}
                value={path}
                onChange={e => setPath(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') onLoadFromPath() }}
                placeholder="C:\Users\...\pipeline.athena"
              />
              <button
                onClick={() => onLoadFromPath()}
                disabled={loading || !path.trim()}
                style={{
                  padding: '8px 14px', borderRadius: 6, border: 'none', flexShrink: 0,
                  background: loading || !path.trim() ? 'var(--accent)80' : 'var(--accent)',
                  color: 'white', cursor: loading || !path.trim() ? 'not-allowed' : 'pointer',
                  fontSize: 12, fontWeight: 600,
                }}
              >
                {loading ? '…' : 'Load'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
