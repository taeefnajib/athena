import { useEffect, useState } from 'react'

interface ResourceItem { path: string; name: string; kind: string }

/** A resource (endpoint, table, ...) of the connection chosen in a sibling field, from
 *  GET /api/connections/{name}/resources. Falls back to free text when there's no connection or no list. */
export function ResourceField({ value, connection, onChange }: { value: string; connection: string; onChange: (v: string) => void }) {
  const [items, setItems] = useState<ResourceItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setItems(null); setError(null)
    if (!connection) return
    let alive = true
    fetch(`/api/connections/${encodeURIComponent(connection)}/resources`)
      .then(async r => {
        const body = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(body?.detail?.detail ?? body?.detail ?? `HTTP ${r.status}`)
        return (body.resources ?? []) as ResourceItem[]
      })
      .then(list => { if (alive) setItems(list) })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
    return () => { alive = false }
  }, [connection])

  const style: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '6px 10px', outline: 'none', fontFamily: 'var(--font)', width: '100%' }
  if (!items || items.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <input style={style} value={value} onChange={e => onChange(e.target.value)} placeholder={connection ? 'Loading resources…' : 'Choose a connection first'} />
        {error && <div style={{ fontSize: 10, color: 'var(--warning)' }}>Couldn't list resources: {error}</div>}
      </div>
    )
  }
  const known = items.some(i => i.path === value)
  return (
    <select style={{ ...style, cursor: 'pointer' }} value={value} onChange={e => onChange(e.target.value)}>
      <option value="">Choose…</option>
      {items.map(i => <option key={i.path} value={i.path}>{i.name}</option>)}
      {value && !known && <option value={value}>{value} (not offered by this connection)</option>}
    </select>
  )
}
