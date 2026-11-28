import { useCallback, useEffect, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { NODE_REGISTRY } from '../../registry/nodeRegistry'

interface Feature { name: string; kind: string; dtype: string; example: unknown }
interface Bundle {
  name: string; slug: string; path: string; model: string; task: string; version: string; features: Feature[]; classes: unknown[]
  source: { pipeline?: string; node_label?: string; run_id?: string }
  preprocessing_not_included: string[]; preprocessing_replayed: string[]; training_only: string[]
  preprocessing_verified: boolean; preprocessing_note: string; needs_athena: boolean
  evaluation: Array<{ node: string; id: string; report: Record<string, number> }>
  quality_gates: Array<{ node: string; id: string; rules: string; on_fail: string; passed: boolean | null }>
  endpoint: { running: boolean; url: string | null }
}

const btn: React.CSSProperties = { fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }
const primary: React.CSSProperties = { ...btn, background: 'var(--accent)', borderColor: 'var(--accent)', color: 'white' }
const label: React.CSSProperties = { fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '16px 0 6px' }
const mono: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 11.5 }

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.detail?.detail ?? `HTTP ${res.status}`)
  return body as T
}

/** Packaged models: build a bundle from a model output, run it as a local endpoint, test it, download it. */
export function ServingModal() {
  const { deployTarget, setShowServingModal, showToast } = useUiStore()
  const toPipelineSpec = usePipelineStore(s => s.toPipelineSpec)
  const node = usePipelineStore(s => s.nodes.find(n => n.id === deployTarget?.nodeId))
  const meta = usePipelineStore(s => s.meta)
  const runId = useExecutionStore(s => s.runId)
  const [bundles, setBundles] = useState<Bundle[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState(() => [meta.name && meta.name !== 'untitled' ? meta.name : '', node ? NODE_REGISTRY[node.type]?.label ?? node.type : 'model'].filter(Boolean).join(' '))
  const [busy, setBusy] = useState<string | null>(null)
  const [request, setRequest] = useState('')
  const [response, setResponse] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const close = () => setShowServingModal(false)

  const refresh = useCallback(async (focus?: string) => {
    const { bundles: list } = await call<{ bundles: Bundle[] }>('/api/serving/bundles')
    setBundles(list)
    setSelected(s => focus ?? s ?? list[0]?.slug ?? null)
  }, [])
  useEffect(() => { refresh().catch(e => showToast(String(e), 'error')) }, [refresh, showToast])

  const current = bundles.find(b => b.slug === selected)
  useEffect(() => {
    if (!current) return
    setRequest(JSON.stringify({ rows: [Object.fromEntries(current.features.map(f => [f.name, f.example]))] }, null, 2))
    setResponse(null); setConfirmDelete(false)
  }, [current?.slug, current?.version])  // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(what)
    try { await fn() } catch (e) { showToast(e instanceof Error ? e.message : String(e), 'error') } finally { setBusy(null) }
  }
  const create = () => act('create', async () => {
    if (!deployTarget || !runId) throw new Error('Run the pipeline first: the model comes from the last run')
    const b = await call<Bundle>('/api/serving/bundles', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, spec: toPipelineSpec(), run_id: runId, node_id: deployTarget.nodeId, port: deployTarget.port }) })
    useUiStore.setState({ deployTarget: null })
    await refresh(b.slug)
    showToast(`Packaged "${b.name}"`, 'success')
  })
  const start = (slug: string) => act('start', async () => { await call(`/api/serving/endpoints/${slug}`, { method: 'POST' }); await refresh(slug) })
  const stop = (slug: string) => act('stop', async () => { await call(`/api/serving/endpoints/${slug}`, { method: 'DELETE' }); await refresh(slug) })
  const remove = (slug: string) => act('delete', async () => { await call(`/api/serving/bundles/${slug}`, { method: 'DELETE' }); setSelected(null); await refresh() })
  const test = (slug: string) => act('predict', async () => {
    let body: unknown
    try { body = JSON.parse(request) } catch { throw new Error('The request must be valid JSON') }
    const res = await call<{ status: number; response: unknown }>(`/api/serving/endpoints/${slug}/predict`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    setResponse(`HTTP ${res.status}\n${JSON.stringify(res.response, null, 2)}`)
  })

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={close}>
      <div role="dialog" aria-label="Serving" onClick={e => e.stopPropagation()}
           style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 'min(1040px, calc(100vw - 32px))', height: 'min(720px, calc(100vh - 48px))', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Serving</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Package a trained model as a prediction service; run it locally, or as Docker / BentoML</div>
          </div>
          <button onClick={close} aria-label="Close" style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          <div style={{ width: 250, borderRight: '1px solid var(--border)', padding: 14, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {deployTarget && (
              <div style={{ padding: 10, border: '1px solid var(--accent)', borderRadius: 8, marginBottom: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 6 }}>Package <strong>{node ? NODE_REGISTRY[node.type]?.label ?? node.type : deployTarget.nodeId}</strong> from the last run</div>
                <input value={name} onChange={e => setName(e.target.value)} aria-label="Model name" placeholder="Model name"
                       style={{ width: '100%', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px', color: 'var(--text)', fontSize: 12, marginBottom: 6 }} />
                <button style={{ ...primary, width: '100%' }} disabled={busy === 'create' || !name.trim()} onClick={create}>{busy === 'create' ? 'Packaging…' : 'Package model'}</button>
              </div>
            )}
            {bundles.length === 0 && !deployTarget && (
              <div style={{ fontSize: 11.5, color: 'var(--text-muted)', lineHeight: 1.6 }}>No packaged models yet. After a run, select a model node, open <strong>Preview</strong> and choose <strong>Deploy</strong>.</div>
            )}
            {bundles.map(b => (
              <button key={b.slug} onClick={() => setSelected(b.slug)}
                      style={{ textAlign: 'left', padding: '7px 8px', borderRadius: 6, border: 'none', cursor: 'pointer', background: selected === b.slug ? 'var(--card2)' : 'transparent', color: 'var(--text)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: b.endpoint.running ? 'var(--success)' : 'transparent', border: b.endpoint.running ? 'none' : '1.5px solid var(--border2)' }} />
                  <span style={{ flex: 1 }}>{b.name}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 13 }}>{b.model} · {b.endpoint.running ? 'running' : 'stopped'}</div>
              </button>
            ))}
          </div>
          <div style={{ flex: 1, padding: '6px 22px 18px', overflowY: 'auto' }}>
            {!current && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 14 }}>{deployTarget ? 'Name the model and package it.' : 'Pick a packaged model.'}</div>}
            {current && (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{current.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{current.model} · {current.task} · {current.features.length} features · from {current.source.node_label} in {current.source.pipeline}</div>
                  </div>
                  {current.endpoint.running
                    ? <button style={btn} disabled={busy === 'stop'} onClick={() => stop(current.slug)}>Stop endpoint</button>
                    : <button style={primary} disabled={busy === 'start'} onClick={() => start(current.slug)}>{busy === 'start' ? 'Starting…' : 'Start endpoint'}</button>}
                  <a style={{ ...btn, textDecoration: 'none' }} href={`/api/serving/bundles/${current.slug}/download`} download>Download .zip</a>
                  <button style={{ ...btn, color: confirmDelete ? 'var(--error)' : 'var(--text)' }} onClick={() => (confirmDelete ? remove(current.slug) : setConfirmDelete(true))}>
                    {confirmDelete ? 'Delete?' : 'Delete'}
                  </button>
                </div>
                {current.preprocessing_replayed.length > 0 && (
                  <div role="note" style={{ marginTop: 12, padding: '8px 12px', border: '1px solid var(--border2)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>
                    ✓ <strong>Takes raw rows.</strong> The service replays the pipeline's fitted preprocessing before predicting:{' '}
                    {current.preprocessing_replayed.join(' → ')}.
                    {current.preprocessing_verified && <span style={{ color: 'var(--text-muted)' }}> Checked: it reproduces the training features exactly.</span>}
                    {current.training_only.length > 0 && <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>Training-only steps, skipped when serving: {current.training_only.join(', ')}.</div>}
                  </div>
                )}
                {current.preprocessing_note && (
                  <div role="note" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-dim)' }}>{current.preprocessing_note}</div>
                )}
                {current.preprocessing_not_included.length > 0 && (
                  <div role="note" style={{ marginTop: 12, padding: '8px 12px', border: '1px solid var(--warning)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>
                    ⚠ <strong>Send partly preprocessed features.</strong> These steps can't be replayed yet, so requests must already reflect them:{' '}
                    {current.preprocessing_not_included.join(', ')}.
                  </div>
                )}
                {current.needs_athena && (
                  <div role="note" style={{ marginTop: 8, padding: '8px 12px', border: '1px solid var(--border2)', borderRadius: 8, fontSize: 12, color: 'var(--text-dim)' }}>
                    This model uses an Athena estimator class: outside Athena, also <span style={mono}>pip install athena-backend</span>.
                  </div>
                )}
                {current.endpoint.running && current.endpoint.url && (
                  <>
                    <div style={label}>Endpoint</div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                      <span style={mono}>POST {current.endpoint.url}/predict</span> · <a href={`${current.endpoint.url}/docs`} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>API docs</a> · local only (127.0.0.1)
                    </div>
                    <div style={label}>Test</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <textarea value={request} onChange={e => setRequest(e.target.value)} aria-label="Request" spellCheck={false}
                                style={{ ...mono, minHeight: 180, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', padding: 8, resize: 'vertical' }} />
                      <pre aria-label="Response" style={{ ...mono, margin: 0, minHeight: 180, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-dim)', padding: 8, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                        {response ?? 'The response appears here.'}
                      </pre>
                    </div>
                    <button style={{ ...primary, marginTop: 8 }} disabled={busy === 'predict'} onClick={() => test(current.slug)}>{busy === 'predict' ? 'Predicting…' : 'Send request'}</button>
                  </>
                )}
                <div style={label}>Quality gates</div>
                {current.quality_gates.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No Quality Gate checked this model. Add one between the model and its consumers to block weak models (e.g. f1 &gt;= 0.9).</div>
                )}
                {current.quality_gates.map(g => (
                  <div key={g.id} style={{ fontSize: 12, color: 'var(--text)', marginBottom: 4 }}>
                    {g.passed === true ? '✓ Passed' : g.passed === false ? '⚠ Failed (warn only)' : '⚠ Did not pass in this run'} · {g.node}{' '}
                    <span style={{ ...mono, color: 'var(--text-dim)' }}>{g.rules.split('\n').filter(Boolean).join(' · ')}</span>
                  </div>
                ))}
                {current.evaluation.length > 0 && (
                  <>
                    <div style={label}>Evaluation</div>
                    {current.evaluation.map(ev => (
                      <div key={ev.id} style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4 }}>
                        <span style={{ color: 'var(--text)' }}>{ev.node}</span>:{' '}
                        <span style={mono}>{Object.entries(ev.report).slice(0, 6).map(([k, v]) => `${k} ${Number.isInteger(v) ? v : v.toFixed(3)}`).join(' · ')}</span>
                      </div>
                    ))}
                  </>
                )}
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>The bundle's MODEL_CARD.md records all of this, with sections to complete (intended use, limitations).</div>
                <div style={label}>Features</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {current.features.map(f => <span key={f.name} style={{ ...mono, fontSize: 11, padding: '2px 8px', borderRadius: 99, border: '1px solid var(--border2)', color: 'var(--text-dim)' }}>{f.name}: {f.kind}</span>)}
                </div>
                <div style={label}>Run it elsewhere</div>
                <pre style={{ ...mono, margin: 0, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-dim)', padding: 10, whiteSpace: 'pre-wrap' }}>
{`# from the unzipped folder (${current.slug}/), no Athena needed
pip install -r requirements.txt && python service.py --port 8000
docker build -t ${current.slug} . && docker run -p 8000:8000 ${current.slug}
bentoml serve service_bentoml:AthenaModel     # pip install bentoml`}
                </pre>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
