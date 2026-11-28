import { useCallback, useEffect, useState } from 'react'

export interface KServeRecord { connection: string; namespace: string; name: string; image: string; min_replicas: number; max_replicas: number }
export interface KServeStatus extends Partial<KServeRecord> {
  deployed: boolean; ready?: boolean; url?: string; predict_url?: string; message?: string
  conditions?: Array<{ type: string; status: string; reason: string; message: string }>
}

const btn: React.CSSProperties = { fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }
const input: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px', color: 'var(--text)', fontSize: 12 }
const mono: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 11.5 }

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.detail?.detail ?? `HTTP ${res.status}`)
  return body as T
}

/** An image with no registry or repository in its name (churn-model:latest) exists only on this machine: a cluster can't pull it. */
export function looksLocal(image: string): boolean {
  return !!image && !image.includes('/')
}

/** Deploy the bundle's image to KServe through a Kubernetes connection, follow it until Ready, or download the manifest. */
export function KServeSection({ slug, record, lastImage, onError }: {
  slug: string; record: KServeRecord | null | undefined; lastImage: string; onError: (message: string) => void
}) {
  const [connections, setConnections] = useState<string[]>([])
  const [connection, setConnection] = useState(record?.connection ?? '')
  const [image, setImage] = useState(record?.image || lastImage)
  const [replicas, setReplicas] = useState({ min: record?.min_replicas ?? 1, max: record?.max_replicas ?? 1 })
  const [status, setStatus] = useState<KServeStatus | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    call<{ connections: Array<{ name: string; type: string }> }>('/api/connections')
      .then(({ connections: list }) => {
        const names = list.filter(c => c.type === 'kubernetes').map(c => c.name)
        setConnections(names)
        setConnection(c => c || names[0] || '')
      }).catch(() => setConnections([]))
  }, [])
  useEffect(() => { setImage(i => i || lastImage) }, [lastImage])

  const refresh = useCallback(async () => {
    try { setStatus(await call<KServeStatus>(`/api/serving/bundles/${slug}/kserve`)) } catch (e) { setStatus({ deployed: false, message: e instanceof Error ? e.message : String(e) }) }
  }, [slug])
  useEffect(() => { if (record) refresh() }, [record, refresh])
  useEffect(() => {  // follow a deployment until it's ready
    if (!status?.deployed || status.ready) return
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [status?.deployed, status?.ready, refresh])

  const act = async (fn: () => Promise<void>) => {
    setBusy(true)
    try { await fn() } catch (e) { onError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const deploy = () => act(async () => {
    setStatus(await call<KServeStatus>(`/api/serving/bundles/${slug}/kserve`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ connection, image, min_replicas: replicas.min, max_replicas: replicas.max }) }))
  })
  const remove = () => act(async () => { await call(`/api/serving/bundles/${slug}/kserve`, { method: 'DELETE' }); setStatus({ deployed: false }) })
  const manifest = `/api/serving/bundles/${slug}/kserve/manifest?${new URLSearchParams({ image, connection, min_replicas: String(replicas.min), max_replicas: String(replicas.max) })}`

  return (
    <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.6 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 10px', alignItems: 'center' }}>
        <label htmlFor={`ks-conn-${slug}`}>Cluster</label>
        {connections.length ? (
          <select id={`ks-conn-${slug}`} style={input} value={connection} onChange={e => setConnection(e.target.value)}>
            {connections.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        ) : <span style={{ color: 'var(--text-muted)' }}>Add a Kubernetes cluster connection (Connections) to deploy from here, or download the manifest.</span>}
        <label htmlFor={`ks-image-${slug}`}>Image</label>
        <input id={`ks-image-${slug}`} style={{ ...input, ...mono }} value={image} placeholder="ghcr.io/you/model:1 (build and push it above)" onChange={e => setImage(e.target.value)} spellCheck={false} />
        <span>Replicas</span>
        <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input aria-label="Minimum replicas" type="number" min={0} style={{ ...input, width: 64 }} value={replicas.min} onChange={e => setReplicas(r => ({ ...r, min: Math.max(0, Number(e.target.value) || 0) }))} />
          to
          <input aria-label="Maximum replicas" type="number" min={1} style={{ ...input, width: 64 }} value={replicas.max} onChange={e => setReplicas(r => ({ ...r, max: Math.max(1, Number(e.target.value) || 1) }))} />
          <span style={{ color: 'var(--text-muted)' }}>(0 minimum scales to zero when idle)</span>
        </span>
      </div>
      {looksLocal(image) && <div style={{ color: 'var(--warning)', marginTop: 4 }}>{image} has no registry in its name: the cluster can't pull it. Name it like ghcr.io/you/{slug}:1, build and push.</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <button style={{ ...btn, background: 'var(--accent)', borderColor: 'var(--accent)', color: 'white' }} disabled={busy || !connection || !image} onClick={deploy}>
          {status?.deployed ? 'Update on KServe' : 'Deploy to KServe'}
        </button>
        {status?.deployed && <button style={btn} disabled={busy} onClick={remove}>Delete from KServe</button>}
        <a style={{ ...btn, textDecoration: 'none' }} href={manifest} download>Download manifest</a>
      </div>
      {status && (status.deployed || status.message) && (
        <div role="status" style={{ marginTop: 8 }}>
          {status.deployed && (status.ready
            ? <span style={{ color: 'var(--success)' }}>✓ Ready in {status.namespace} · <span style={mono}>POST {status.predict_url}</span></span>
            : <span style={{ color: 'var(--running)' }}>Deploying {status.name} in {status.namespace}… (checking every 5 s)</span>)}
          {status.message && <div style={{ color: status.deployed ? 'var(--text-muted)' : 'var(--warning)' }}>{status.message}</div>}
        </div>
      )}
      <div style={{ color: 'var(--text-muted)', marginTop: 6 }}>
        The InferenceService runs this bundle's image and answers KServe's V1 protocol (<span style={mono}>{'{"instances": [...]}'}</span>) as well as <span style={mono}>/predict</span>.
      </div>
    </div>
  )
}
