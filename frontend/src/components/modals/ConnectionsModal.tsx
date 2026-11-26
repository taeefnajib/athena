import { useEffect, useMemo, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { useConnectionStore } from '../../store/connectionStore'
import { connectionsApi, type SavedConnection, type TestResult } from '../../lib/connections'
import type { ConfigField } from '../../registry/nodeRegistry'

type Draft = { name: string; type: string; values: Record<string, unknown>; saved: SavedConnection | null }

const input: React.CSSProperties = {
  background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)',
  fontSize: 12, padding: '6px 10px', outline: 'none', fontFamily: 'var(--font)', width: '100%',
}
const label: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: 'var(--text-dim)' }
const btn = (primary = false): React.CSSProperties => ({
  padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer', fontFamily: 'var(--font)',
  border: primary ? '1px solid transparent' : '1px solid var(--border)',
  background: primary ? 'var(--accent)' : 'var(--card)', color: primary ? 'white' : 'var(--text)',
})

export function ConnectionsModal() {
  const { setShowConnectionsModal, showToast } = useUiStore()
  const { connectors, connections, loaded, load, save, remove } = useConnectionStore()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [test, setTest] = useState<TestResult | null>(null)
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)

  useEffect(() => { load().catch(e => showToast(`Couldn't load connections: ${e.message}`, 'error')) }, [load, showToast])

  const spec = useMemo(() => connectors.find(c => c.type === draft?.type), [connectors, draft?.type])

  const startNew = (type: string) => {
    const c = connectors.find(x => x.type === type)
    if (!c) return
    setDraft({ name: '', type, values: Object.fromEntries(c.config.map(f => [f.id, f.default])), saved: null })
    setTest(null)
  }
  const edit = (conn: SavedConnection) => {
    const c = connectors.find(x => x.type === conn.type)
    const values = Object.fromEntries((c?.config ?? []).map(f => [f.id, conn.config[f.id] ?? f.default]))
    for (const [f, s] of Object.entries(conn.secrets)) values[f] = s.ref ?? ''  // keychain secrets stay empty = keep
    setDraft({ name: conn.name, type: conn.type, values, saved: conn })
    setTest(null)
  }

  const runTest = async () => {
    if (!draft) return
    setBusy('test')
    try { setTest(await connectionsApi.test(draft.type, draft.values, draft.saved?.name)) }
    catch (e) { setTest({ ok: false, message: e instanceof Error ? e.message : String(e), details: {} }) }
    finally { setBusy(null) }
  }
  const runSave = async () => {
    if (!draft) return
    setBusy('save')
    try {
      const saved = await save(draft.name.trim(), draft.type, draft.values)
      showToast(`Saved connection "${saved.name}"`, 'success')
      edit(saved)
    } catch (e) { showToast(e instanceof Error ? e.message : String(e), 'error') }
    finally { setBusy(null) }
  }
  const runDelete = async () => {
    if (!draft?.saved) return
    try { await remove(draft.saved.name); setDraft(null); showToast('Connection deleted', 'success') }
    catch (e) { showToast(e instanceof Error ? e.message : String(e), 'error') }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowConnectionsModal(false)}>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 760, height: 560, display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Connections</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Secrets are stored in your OS keychain, never in pipeline files or exported code.</div>
          </div>
          <button onClick={() => setShowConnectionsModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          <div style={{ width: 230, borderRight: '1px solid var(--border)', padding: 12, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {!loaded && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading…</div>}
            {loaded && connections.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>No connections yet.</div>}
            {connections.map(c => (
              <div key={c.name} onClick={() => edit(c)} style={{ padding: '8px 10px', borderRadius: 8, cursor: 'pointer', border: '1px solid', borderColor: draft?.saved?.name === c.name ? 'var(--accent)' : 'var(--border)', background: draft?.saved?.name === c.name ? 'var(--card)' : 'transparent' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{c.name}</div>
                <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2 }}>{c.label}{String(c.config.dialect ?? c.config.protocol ?? '') && ` · ${String(c.config.dialect ?? c.config.protocol)}`}</div>
              </div>
            ))}
            <div style={{ marginTop: 'auto', paddingTop: 10, borderTop: '1px solid var(--border)' }}>
              <div style={{ ...label, marginBottom: 6 }}>New connection</div>
              {connectors.map(c => (
                <button key={c.type} onClick={() => startNew(c.type)} style={{ ...btn(), width: '100%', textAlign: 'left', marginBottom: 6 }}>＋ {c.label}</button>
              ))}
            </div>
          </div>
          <div style={{ flex: 1, padding: 18, overflowY: 'auto' }}>
            {!draft || !spec ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.7 }}>Pick a connection, or create one. Nodes refer to connections by name, so pipelines can be shared without sharing credentials.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{spec.description} <span style={{ color: 'var(--text-dim)' }}>Uses {spec.library} · {spec.license}</span></div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={label}>Name</label>
                  <input style={input} value={draft.name} disabled={!!draft.saved} placeholder="e.g. warehouse" onChange={e => setDraft({ ...draft, name: e.target.value })} />
                </div>
                {spec.config.map(f => (
                  <FormField key={f.id} field={f} value={draft.values[f.id]}
                    savedSecret={!!draft.saved?.secrets[f.id]?.set && !draft.saved?.secrets[f.id]?.ref}
                    onChange={v => setDraft({ ...draft, values: { ...draft.values, [f.id]: v } })} />
                ))}
                {Object.keys(spec.extras).length > 0 && (
                  <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                    Drivers: {Object.entries(spec.extras).map(([k, v]) => <div key={k}>{k}: <code style={{ fontFamily: 'var(--mono)' }}>{v}</code></div>)}
                  </div>
                )}
                {test && (
                  <div style={{ fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid', borderColor: test.ok ? 'var(--success)' : 'var(--error)', color: test.ok ? 'var(--success)' : 'var(--error)', wordBreak: 'break-word' }}>
                    {test.ok ? '✓ ' : '✕ '}{test.message}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button style={btn()} disabled={busy !== null} onClick={runTest}>{busy === 'test' ? 'Testing…' : 'Test connection'}</button>
                  <button style={btn(true)} disabled={busy !== null || !draft.name.trim()} onClick={runSave}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
                  {draft.saved && <button style={{ ...btn(), marginLeft: 'auto', color: 'var(--error)' }} onClick={runDelete}>Delete</button>}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function FormField({ field, value, onChange, savedSecret }: { field: ConfigField; value: unknown; onChange: (v: unknown) => void; savedSecret: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <label style={label}>{field.label}</label>
      {field.type === 'select' ? (
        <select style={{ ...input, cursor: 'pointer' }} value={String(value)} onChange={e => onChange(e.target.value)}>
          {field.options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : field.type === 'number' ? (
        <input style={input} type="number" value={Number(value)} onChange={e => onChange(Number(e.target.value))} />
      ) : field.type === 'toggle' ? (
        <input type="checkbox" checked={Boolean(value)} onChange={e => onChange(e.target.checked)} />
      ) : field.type === 'password' ? (
        <input style={input} type="password" autoComplete="new-password" value={String(value ?? '')}
          placeholder={savedSecret ? '•••••• saved in keychain (leave empty to keep)' : ''} onChange={e => onChange(e.target.value)} />
      ) : (
        <input style={input} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />
      )}
      {field.help && <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>{field.help}</div>}
    </div>
  )
}
