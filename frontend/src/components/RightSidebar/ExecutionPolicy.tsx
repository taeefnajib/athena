import { useEffect, useState } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import type { NodePolicy } from '../../types/pipeline'

const input: React.CSSProperties = {
  background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)',
  fontSize: 12, padding: '5px 8px', outline: 'none', fontFamily: 'var(--font)', width: '100%',
}
const label: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: 'var(--text-dim)' }
const hint: React.CSSProperties = { fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }

export interface RuntimeOption { value: string; label: string; available: boolean; hint: string | null }
let runtimesCache: Promise<RuntimeOption[]> | null = null
function loadRuntimes(): Promise<RuntimeOption[]> {
  runtimesCache ??= fetch('/api/runtimes').then(r => r.json()).then(b => b.runtimes as RuntimeOption[]).catch(() => { runtimesCache = null; return [] })
  return runtimesCache
}

/** Resource requests as the spec wants them: empty fields dropped, all-empty = null. */
export function cleanResources(r: NonNullable<NodePolicy['resources']>): NodePolicy['resources'] {
  const out = Object.fromEntries(Object.entries(r).filter(([, v]) => v != null && !Number.isNaN(v) && (v as number) > 0))
  return Object.keys(out).length ? out : null
}

/** Per-node execution policy (workflow spec v2): where it runs, resources, timeout, retries, caching. */
export function ExecutionPolicy({ nodeId }: { nodeId: string }) {
  const policy = usePipelineStore(s => s.nodes.find(n => n.id === nodeId)?.policy) ?? {}
  const update = usePipelineStore(s => s.updateNodePolicy)
  const isSet = policy.timeout_s != null || policy.retry != null || policy.cache === false || !!policy.runtime || !!policy.resources
  const [runtimes, setRuntimes] = useState<RuntimeOption[]>([])
  useEffect(() => { loadRuntimes().then(setRuntimes) }, [])
  const [open, setOpen] = useState(isSet)
  const set = (patch: NodePolicy) => update(nodeId, { ...policy, ...patch })
  const attempts = policy.retry?.max_attempts ?? 1
  const backoff = policy.retry?.backoff_s ?? 0
  const res = policy.resources ?? {}
  const onRay = (policy.runtime ?? '').startsWith('ray')
  const onK8s = (policy.runtime ?? '').startsWith('k8s')
  const onRunner = (policy.runtime ?? '').startsWith('runner')
  const chosen = runtimes.find(r => r.value === (policy.runtime || 'python'))
  const setRes = (key: 'cpu' | 'memory_gb' | 'gpu', raw: string) => set({ resources: cleanResources({ ...res, [key]: raw === '' ? null : Number(raw) }) })

  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '10px 16px 14px' }}>
      <div onClick={() => setOpen(!open)} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
        <span style={{ ...label, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 10 }}>Execution</span>
        <span style={{ fontSize: 10, color: isSet ? 'var(--accent)' : 'var(--text-muted)' }}>{isSet ? 'custom' : 'defaults'} {open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={label} htmlFor={`runtime-${nodeId}`}>Runs on</label>
            <select id={`runtime-${nodeId}`} style={input} value={policy.runtime || 'python'}
              onChange={e => set({ runtime: e.target.value === 'python' ? null : e.target.value })}>
              {(runtimes.length ? runtimes : [{ value: 'python', label: 'Local worker', available: true, hint: null }]).map(r => (
                <option key={r.value} value={r.value} disabled={!r.available && r.value !== policy.runtime}>{r.label}{r.available ? '' : ' (not installed)'}</option>
              ))}
              {policy.runtime && !runtimes.some(r => r.value === policy.runtime) && <option value={policy.runtime}>{policy.runtime} (missing)</option>}
            </select>
            {chosen?.hint && <div style={{ ...hint, color: 'var(--warning)' }}>{chosen.hint}</div>}
            {onRunner && <div style={hint}>Runs on the machine serving athena-runner; its logs stream here while it runs and Stop cancels it there. File paths in this node's settings are that machine's.</div>}
            {onK8s && <div style={hint}>Runs as a Kubernetes Job in the connection's image; inputs and outputs go through its artifact store. Stop deletes the Job, and the node's timeout is the Job's deadline. Logs arrive when the node finishes.</div>}
            {onRay && <div style={hint}>Runs as a Ray task (a local cluster starts with the run, which takes a few seconds; add a Ray cluster under Connections for a remote one). Logs arrive when the node finishes; n_jobs work spreads over the cluster.</div>}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {([['cpu', 'CPUs'], ['memory_gb', 'Memory (GB)'], ['gpu', 'GPUs']] as const).map(([key, text]) => (
              <div key={key} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label style={label}>{text}</label>
                <input style={input} type="number" min={0} step={key === 'gpu' ? 1 : 0.5} placeholder="—" aria-label={text}
                  value={res[key] ?? ''} onChange={e => setRes(key, e.target.value)} />
              </div>
            ))}
          </div>
          <div style={hint}>{onRay ? 'Reserved on the Ray cluster for this node.' : onK8s ? "The pod's requests and limits (GPUs as nvidia.com/gpu)." : onRunner ? 'Advisory on a runner (it runs a fixed number of jobs at once).' : 'Advisory on the local worker; enforced when the node runs on Ray or Kubernetes.'}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={label}>Timeout (seconds)</label>
            <input style={input} type="number" min={1} placeholder="default (ATHENA_NODE_TIMEOUT_S)"
              value={policy.timeout_s ?? ''} onChange={e => set({ timeout_s: e.target.value === '' ? null : Math.max(1, Number(e.target.value)) })} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={label}>Attempts</label>
              <input style={input} type="number" min={1} max={10} value={attempts}
                onChange={e => {
                  const n = Math.min(10, Math.max(1, Number(e.target.value) || 1))
                  set({ retry: n === 1 && backoff === 0 ? null : { max_attempts: n, backoff_s: backoff } })
                }} />
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={label}>Backoff (s)</label>
              <input style={input} type="number" min={0} max={300} value={backoff} disabled={attempts === 1}
                onChange={e => set({ retry: { max_attempts: attempts, backoff_s: Math.min(300, Math.max(0, Number(e.target.value) || 0)) } })} />
            </div>
          </div>
          <div style={hint}>Retries re-run the node after an error, waiting the backoff (doubling each time). Timeouts and Stop are not retried.</div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}>
            <input type="checkbox" checked={policy.cache !== false} onChange={e => set({ cache: e.target.checked })} />
            Reuse cached result when inputs and settings are unchanged
          </label>
          {policy.cache === false && <div style={hint}>This node always re-runs (useful for nodes that read live data).</div>}
        </div>
      )}
    </div>
  )
}
