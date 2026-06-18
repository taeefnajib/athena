import { useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { api } from '../../lib/api'

export function SaveModal() {
  const { setShowSaveModal, showToast } = useUiStore()
  const toPipelineSpec = usePipelineStore(s => s.toPipelineSpec)
  const [name, setName] = useState('')
  const [customPath, setCustomPath] = useState('')
  const [useCustom, setUseCustom] = useState(false)
  const [saving, setSaving] = useState(false)

  const onSave = async () => {
    const target = useCustom ? customPath.trim() : name.trim()
    if (!target) return
    setSaving(true)
    try {
      const res = await api.savePipeline(target, toPipelineSpec())
      const savedPath = (res as { ok: boolean; path?: string }).path ?? target
      showToast(`Saved → ${savedPath}`, 'success')
      setShowSaveModal(false)
    } catch {
      showToast('Save failed — check the path is writable', 'error')
    } finally {
      setSaving(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6,
    padding: '8px 10px', color: 'var(--text)', fontSize: 13, outline: 'none',
    fontFamily: 'var(--mono)', width: '100%', boxSizing: 'border-box', transition: 'border-color 0.15s',
  }

  const isReady = useCustom ? customPath.trim().length > 0 : name.trim().length > 0

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={() => setShowSaveModal(false)}
    >
      <div
        style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 440, boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ padding: '18px 20px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Save Pipeline</div>
          <button onClick={() => setShowSaveModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>×</button>
        </div>

        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {!useCustom ? (
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', display: 'block', marginBottom: 6, letterSpacing: '0.02em' }}>
                PIPELINE NAME
              </label>
              <input
                style={inputStyle}
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') onSave() }}
                placeholder="my-pipeline"
                autoFocus
              />
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                Saves to <code style={{ fontFamily: 'var(--mono)' }}>~/.athena/pipelines/{name || 'name'}.athena</code>
              </div>
            </div>
          ) : (
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', display: 'block', marginBottom: 6, letterSpacing: '0.02em' }}>
                CUSTOM PATH
              </label>
              <input
                style={inputStyle}
                value={customPath}
                onChange={e => setCustomPath(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') onSave() }}
                placeholder="C:\Users\...\pipeline.athena"
                autoFocus
              />
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                Full filesystem path. File will be created or overwritten.
              </div>
            </div>
          )}

          <button
            onClick={() => setUseCustom(v => !v)}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 11, textDecoration: 'underline', padding: 0, textAlign: 'left' }}
          >
            {useCustom ? '← Save to pipeline library instead' : 'Save to custom path instead →'}
          </button>

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button
              onClick={() => setShowSaveModal(false)}
              style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer', fontSize: 12, fontWeight: 500 }}
            >
              Cancel
            </button>
            <button
              onClick={onSave}
              disabled={saving || !isReady}
              style={{ padding: '7px 16px', borderRadius: 6, border: 'none', background: saving || !isReady ? 'var(--accent)80' : 'var(--accent)', color: 'white', cursor: saving || !isReady ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 600 }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
