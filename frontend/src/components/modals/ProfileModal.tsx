import { useEffect, useMemo, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { NODE_REGISTRY } from '../../registry/nodeRegistry'
import { artifactUrl, compact, fetchProfile, fmtNum, TABLE_PORT_TYPES, type Profile } from '../../lib/profile'
import { BarList, HistogramChart, Tooltip, useTooltip } from '../profile/Charts'
import { ColumnsTable } from '../profile/ColumnsTable'

const section: React.CSSProperties = { fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '0 0 8px' }
const card: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }
const select: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '5px 8px', fontFamily: 'var(--font)' }
const link: React.CSSProperties = { fontSize: 12, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', textDecoration: 'none' }

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div style={{ ...card, padding: '10px 14px', minWidth: 110, flex: 1 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: 'var(--text)', marginTop: 2 }}>{value}</div>
      {note && <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2 }}>{note}</div>}
    </div>
  )
}

/** Profile of one table output of a node from the last run: schema, statistics, findings, target association. */
export function ProfileModal() {
  const { profileTarget, setProfileTarget } = useUiStore()
  const node = usePipelineStore(s => s.nodes.find(n => n.id === profileTarget?.nodeId))
  const runId = useExecutionStore(s => s.runId)
  const spec = node ? NODE_REGISTRY[node.type] : undefined
  const ports = useMemo(() => (spec?.outputs ?? []).map((p, i) => ({ ...p, i })).filter(p => TABLE_PORT_TYPES.has(p.type)), [spec])
  const [port, setPort] = useState(profileTarget?.port ?? ports[0]?.i ?? 0)
  const [target, setTarget] = useState('')
  const [profile, setProfile] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const chartTip = useTooltip()
  const close = () => setProfileTarget(null)

  useEffect(() => {
    if (!runId || !node) return
    setLoading(true); setError(null)
    fetchProfile(runId, node.id, port, target)
      .then(p => setProfile(p))
      .catch(e => { setError(e instanceof Error ? e.message : String(e)); setProfile(null) })
      .finally(() => setLoading(false))
  }, [runId, node, port, target])

  if (!node || !spec) return null
  const flagged = new Set((profile?.insights ?? []).map(i => i.column).filter((c): c is string => !!c))
  const ov = profile?.overview

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={close}>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 'min(1180px, 95vw)', height: 'min(820px, 92vh)', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Data profile · {spec.label}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {ov ? `${ov.rows.toLocaleString()} rows × ${ov.columns} columns` : ' '}{ov?.sampled ? ` · statistics from a random sample of ${ov.profiled_rows.toLocaleString()} rows` : ''}
            </div>
          </div>
          {ports.length > 1 && (
            <select style={select} value={port} onChange={e => setPort(Number(e.target.value))} aria-label="Output">
              {ports.map(p => <option key={p.i} value={p.i}>{p.name}</option>)}
            </select>
          )}
          <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
            Target
            <select style={select} value={target} onChange={e => setTarget(e.target.value)}>
              <option value="">{profile?.target ? `auto (${profile.target.name})` : 'auto (a column named target)'}</option>
              {(profile?.columns ?? []).map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          {runId && <a style={link} href={artifactUrl(runId, node.id, port, 'csv')} download>↓ CSV</a>}
          {runId && <a style={link} href={artifactUrl(runId, node.id, port, 'parquet')} download>↓ Parquet</a>}
          <button onClick={close} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }} aria-label="Close">×</button>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 20, opacity: loading && profile ? 0.55 : 1, transition: 'opacity 0.15s' }}>
          {!runId && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Run the pipeline first: profiles are computed from the run's results.</div>}
          {error && <div style={{ fontSize: 12, color: 'var(--error)' }}>{error}</div>}
          {loading && !profile && !error && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Profiling…</div>}
          {profile && ov && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <Stat label="Rows" value={compact(ov.rows)} />
                <Stat label="Columns" value={String(ov.columns)} note={Object.entries(ov.kinds).map(([k, v]) => `${v} ${k}`).join(' · ')} />
                <Stat label="Missing cells" value={`${ov.missing_pct}%`} note={`${ov.missing_cells.toLocaleString()} cells`} />
                <Stat label="Duplicate rows" value={ov.duplicate_rows.toLocaleString()} />
                <Stat label="Memory" value={`${ov.memory_mb} MB`} />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 14 }}>
                <div style={card}>
                  <h3 style={section}>Findings</h3>
                  {profile.insights.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No data-quality problems found.</div>}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {profile.insights.map((f, i) => (
                      <div key={i} style={{ display: 'flex', gap: 8, fontSize: 12, lineHeight: 1.5 }}>
                        <span style={{ flexShrink: 0, color: f.severity === 'warning' ? 'var(--warning)' : 'var(--text-muted)', fontWeight: 600, width: 64 }}>
                          {f.severity === 'warning' ? '⚠ Warning' : 'ⓘ Note'}
                        </span>
                        <span style={{ color: 'var(--text-dim)' }}>{f.column && <strong style={{ color: 'var(--text)' }}>{f.column}: </strong>}{f.message}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={card}>
                  {profile.target ? (
                    <>
                      <h3 style={section}>Target · {profile.target.name} ({profile.target.task})</h3>
                      {profile.target.classes && (
                        <BarList rows={profile.target.classes.map(c => ({ label: c.value, value: c.count, note: `${c.pct}%` }))} valueLabel="rows" tooltip={chartTip} />
                      )}
                      {profile.target.histogram && (
                        <div style={{ width: 420, maxWidth: '100%' }}>
                          <HistogramChart hist={profile.target.histogram} width={420} height={90} tooltip={chartTip} />
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text-muted)', fontFamily: 'var(--mono)', marginTop: 4 }}>
                            <span>{fmtNum(profile.target.histogram.edges[0])}</span>
                            <span>mean {fmtNum(profile.target.mean)}</span>
                            <span>{fmtNum(profile.target.histogram.edges[profile.target.histogram.edges.length - 1])}</span>
                          </div>
                        </div>
                      )}
                      {profile.association.length > 0 && (
                        <>
                          <h3 style={{ ...section, marginTop: 16 }}>What carries information about {profile.target.name}</h3>
                          <BarList rows={profile.association.slice(0, 12).map(a => ({ label: a.column, value: a.score ?? 0 }))}
                                   valueLabel="mutual information" format={v => v.toFixed(3)} tooltip={chartTip} />
                          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>
                            Mutual information with the target, one column at a time (0 = no information). A guide for feature selection, not a model's importance.
                          </div>
                        </>
                      )}
                    </>
                  ) : (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>Choose a target column above to see its distribution and which columns carry information about it.</div>
                  )}
                </div>
              </div>

              <div style={card}>
                <h3 style={section}>Columns</h3>
                <ColumnsTable columns={profile.columns} flagged={flagged} />
              </div>
            </div>
          )}
        </div>
        <Tooltip tip={chartTip.tip} />
      </div>
    </div>
  )
}
