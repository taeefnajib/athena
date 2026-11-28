import { useEffect, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import type { SubflowConfig } from '../../lib/subflow'

interface SavedSubflow { name: string; description: string; nodes: number; inputs: string[]; outputs: string[]; config: SubflowConfig }

/** "My subflows": the reusable subflows saved with "Save to library". Drag one onto the canvas to use it. */
export function SubflowLibrary({ search }: { search: string }) {
  const version = useUiStore(s => s.subflowLibraryVersion)
  const { bumpSubflowLibrary, showToast } = useUiStore()
  const [items, setItems] = useState<SavedSubflow[]>([])
  const [open, setOpen] = useState(true)
  const [confirming, setConfirming] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/subflows').then(r => r.json()).then(b => setItems(b.subflows ?? [])).catch(() => setItems([]))
  }, [version])

  const q = search.toLowerCase()
  const shown = items.filter(s => !q || s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q))
  if (items.length === 0 || (q && shown.length === 0)) return null

  const remove = async (name: string) => {
    const res = await fetch(`/api/subflows/${encodeURIComponent(name)}`, { method: 'DELETE' })
    setConfirming(null)
    if (res.ok) { bumpSubflowLibrary(); showToast(`Deleted "${name}" from your subflows`, 'info') }
    else showToast(`Couldn't delete "${name}"`, 'error')
  }

  return (
    <div>
      <div onClick={() => setOpen(o => !o)}
           style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', cursor: 'pointer', userSelect: 'none', fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', color: 'var(--text-dim)' }}>
        <div style={{ width: 7, height: 7, borderRadius: 2, background: 'var(--cat-subflow)', flexShrink: 0 }} />
        <span>My subflows</span>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--text-muted)', display: 'inline-block', transform: open ? 'none' : 'rotate(-90deg)' }}>▾</span>
      </div>
      {open && shown.map(s => (
        <div key={s.name} draggable title={`${s.nodes} nodes · in: ${s.inputs.join(', ') || '—'} · out: ${s.outputs.join(', ') || '—'}`}
             onDragStart={e => { e.dataTransfer.setData('application/athena-subflow', JSON.stringify(s.config)); e.dataTransfer.effectAllowed = 'copy' }}
             style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px 5px 26px', cursor: 'grab', userSelect: 'none' }}
             onMouseEnter={e => { e.currentTarget.style.background = 'var(--card)' }} onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; setConfirming(c => (c === s.name ? null : c)) }}>
          <div style={{ width: 5, height: 5, borderRadius: 1, background: 'var(--cat-subflow)', flexShrink: 0 }} />
          <span style={{ fontSize: 12, color: 'var(--text-dim)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{s.nodes}</span>
          <button onClick={() => (confirming === s.name ? remove(s.name) : setConfirming(s.name))} aria-label={`Delete ${s.name}`}
                  title={confirming === s.name ? 'Click again to delete' : 'Delete from your subflows'}
                  style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: confirming === s.name ? 10 : 12, padding: '0 2px',
                           color: confirming === s.name ? 'var(--error)' : 'var(--text-muted)' }}>
            {confirming === s.name ? 'Delete?' : '×'}
          </button>
        </div>
      ))}
    </div>
  )
}
