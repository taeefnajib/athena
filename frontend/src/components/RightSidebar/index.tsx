import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { useConnectionStore } from '../../store/connectionStore'
import { NODE_REGISTRY, CATEGORY_META, type NodeSpec, type ConfigField } from '../../registry/nodeRegistry'
import { api } from '../../lib/api'
import { ExecutionPolicy } from './ExecutionPolicy'
import { OutputActions } from './OutputActions'
import { formatMetric } from '../../lib/formatMetric'
import { RunFromHere } from './RunFromHere'
import { ResourceField } from './ResourceField'
import { CodeTab } from './CodeTab'
import { SubflowInspector } from './SubflowInspector'
import { isSubflow } from '../../lib/subflow'
import { CodeEditor } from '../ui/LazyCodeEditor'
import type { ArtifactPreview, LogEntry, ColumnInfo } from '../../types/pipeline'

type HpParam = { key: string; values: string }

export function RightSidebar({ onRunFrom }: { onRunFrom: (nodeId: string) => void }) {
  const selectedNodeId = usePipelineStore(s => s.selectedNodeId)
  const node = usePipelineStore(s => s.nodes.find(n => n.id === selectedNodeId))

  return (
    <AnimatePresence>
      {node && (
        <motion.div
          key="inspector"
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 280, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
          style={{ overflow: 'hidden', flexShrink: 0, height: '100%' }}
        >
          {isSubflow(node.type)
            ? <SubflowInspector key={node.id} nodeId={node.id} config={node.config} onRunFrom={onRunFrom} Preview={PreviewTab} Logs={LogsTab} />
            : <Inspector key={node.id} nodeId={node.id} nodeType={node.type} config={node.config} onRunFrom={onRunFrom} />}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

const EMPTY_LOGS: LogEntry[] = []
const EMPTY_METRICS: Record<string, number> = {}

function Inspector({ nodeId, nodeType, config, onRunFrom }: { nodeId: string; nodeType: string; config: Record<string, unknown>; onRunFrom: (nodeId: string) => void }) {
  const { inspectorTab, setInspectorTab } = useUiStore()
  const nodeState = useExecutionStore(s => s.nodeStates[nodeId])
  const preview = useExecutionStore(s => s.previews[nodeId])
  const logs = useExecutionStore(s => s.logs[nodeId] ?? EMPTY_LOGS)
  const metrics = useExecutionStore(s => s.metrics[nodeId] ?? EMPTY_METRICS)
  const updateConfig = usePipelineStore(s => s.updateNodeConfig)

  const spec = NODE_REGISTRY[nodeType]
  if (!spec) return null
  const catMeta = CATEGORY_META[spec.category]

  const statusMap: Record<string, { color: string; label: string }> = {
    idle:    { color: 'var(--text-muted)', label: 'Idle' },
    running: { color: 'var(--running)',    label: 'Running…' },
    success: { color: 'var(--success)',    label: 'Complete' },
    error:   { color: 'var(--error)',      label: 'Error' },
  }
  const st = statusMap[nodeState?.status ?? 'idle']

  const TABS = ['settings', 'preview', 'logs', 'metrics', 'code'] as const

  return (
    <div style={{ width: 280, minWidth: 280, background: 'var(--panel)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '14px 16px 12px', borderBottom: '1px solid var(--border)', background: `linear-gradient(135deg, ${catMeta.color}18, transparent)` }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px', borderRadius: 99, background: `${catMeta.color}20`, border: `1px solid ${catMeta.color}40`, fontSize: 10, fontWeight: 600, letterSpacing: '0.04em', color: catMeta.color, marginBottom: 6 }}>
          <span>{catMeta.icon}</span><span>{catMeta.label}</span>
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>{spec.label}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 8 }}>{spec.description}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: st.color }} />
          <span style={{ fontSize: 11, color: st.color }}>{st.label}</span>
          {nodeState?.status === 'success' && nodeState.cached && (
            <span title="Reused from an earlier run: this node's settings, the nodes upstream and its input files are unchanged"
                  style={{ fontSize: 10, color: 'var(--text-dim)', padding: '1px 6px', borderRadius: 99, border: '1px solid var(--border2)' }}>cached</span>
          )}
          <RunFromHere nodeId={nodeId} onRunFrom={onRunFrom} />
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>{nodeId.slice(0, 8)}</span>
        </div>
        {nodeState?.error && (
          <div style={{ marginTop: 8, padding: '6px 8px', background: 'var(--error)20', border: '1px solid var(--error)40', borderRadius: 6, fontSize: 11, color: 'var(--error)' }}>
            {nodeState.error.message}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        {TABS.map(t => (
          <div key={t} onClick={() => setInspectorTab(t)} style={{ flex: 1, padding: '8px 4px', textAlign: 'center', fontSize: 11, fontWeight: inspectorTab === t ? 600 : 400, color: inspectorTab === t ? 'var(--accent)' : 'var(--text-muted)', cursor: 'pointer', borderBottom: inspectorTab === t ? '2px solid var(--accent)' : '2px solid transparent', marginBottom: -1, transition: 'color 0.15s', textTransform: 'capitalize' }}>
            {t}
          </div>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {inspectorTab === 'settings' && <SettingsTab spec={spec} config={config} nodeId={nodeId} onChange={updateConfig} />}
        {inspectorTab === 'settings' && <ExecutionPolicy nodeId={nodeId} />}
        {inspectorTab === 'preview'  && <OutputActions nodeId={nodeId} nodeType={nodeType} />}
        {inspectorTab === 'preview'  && <PreviewTab preview={preview} />}
        {inspectorTab === 'logs'     && <LogsTab logs={logs} />}
        {inspectorTab === 'metrics'  && <MetricsTab metrics={metrics} />}
        {inspectorTab === 'code'     && <CodeTab nodeId={nodeId} />}
      </div>
    </div>
  )
}

function SettingsTab({ spec, config, nodeId, onChange }: { spec: NodeSpec; config: Record<string, unknown>; nodeId: string; onChange: (id: string, cfg: Record<string, unknown>) => void }) {
  if (!spec) return null
  const inputBase: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '6px 10px', outline: 'none', fontFamily: 'var(--font)', width: '100%', transition: 'border-color 0.15s' }

  if (!spec.config || spec.config.length === 0) {
    return <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 12 }}>No configurable parameters for this node.</div>
  }

  return (
    <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {spec.config.map((field: ConfigField) => {
        const val = config[field.id] !== undefined ? config[field.id] : field.default
        const update = (v: unknown) => onChange(nodeId, { ...config, [field.id]: v })
        return (
          <div key={field.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', letterSpacing: '0.02em' }}>{field.label}</label>
            {field.type === 'text' && <input style={inputBase} value={String(val)} onChange={e => update(e.target.value)} />}
            {field.type === 'number' && <input style={inputBase} type="number" value={Number(val)} onChange={e => update(Number(e.target.value))} />}
            {field.type === 'select' && (
              <select style={{ ...inputBase, cursor: 'pointer' }} value={String(val)} onChange={e => update(e.target.value)}>
                {field.options.map((o: string) => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {field.type === 'toggle' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div
                  style={{ width: 34, height: 18, borderRadius: 99, background: val ? 'var(--accent)' : 'var(--card2)', border: '1px solid var(--border2)', position: 'relative', cursor: 'pointer', transition: 'background 0.2s', flexShrink: 0 }}
                  onClick={() => update(!val)}
                >
                  <div style={{ position: 'absolute', top: 2, left: val ? 15 : 2, width: 12, height: 12, borderRadius: '50%', background: 'white', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} />
                </div>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{val ? 'Enabled' : 'Disabled'}</span>
              </div>
            )}
            {field.type === 'textarea' && (
              <textarea style={{ ...inputBase, resize: 'vertical', minHeight: 72, fontFamily: field.mono ? 'var(--mono)' : 'var(--font)', fontSize: 11 }} value={String(val)} onChange={e => update(e.target.value)} rows={4} />
            )}
            {field.type === 'file' && (
              <FileField value={String(val)} accept={field.accept} onChange={update} />
            )}
            {field.type === 'hp_params' && (
              <HpParamsField
                value={Array.isArray(val) ? val as HpParam[] : []}
                onChange={update}
              />
            )}
            {field.type === 'col_map' && (
              <ColMapField
                value={Array.isArray(val) ? val as HpParam[] : []}
                onChange={update}
              />
            )}
            {field.type === 'password' && <input style={inputBase} type="password" autoComplete="new-password" value={String(val)} onChange={e => update(e.target.value)} />}
            {field.type === 'code' && (
              <CodeEditor value={String(val)} language={field.language ?? 'python'} onChange={update} ariaLabel={field.label} />
            )}
            {field.type === 'resource' && (
              <ResourceField value={String(val)} onChange={update}
                             connection={String((field.connection_field && config[field.connection_field]) ?? '')} />
            )}
            {field.type === 'connection' && <ConnectionField value={String(val)} connector={field.connector} emptyLabel={field.empty_label} onChange={update} />}
            {field.help && <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>{field.help}</div>}
          </div>
        )
      })}
    </div>
  )
}

function ConnectionField({ value, connector, emptyLabel, onChange }: { value: string; connector?: string; emptyLabel?: string; onChange: (v: string) => void }) {
  const { connections, loaded, load } = useConnectionStore()
  const setShowConnectionsModal = useUiStore(s => s.setShowConnectionsModal)
  useEffect(() => { if (!loaded) load().catch(() => { /* the modal reports load errors */ }) }, [loaded, load])
  const allowed = connector ? connector.split(',').map(t => t.trim()) : null  // one type, or a comma-separated list
  const choices = connections.filter(c => !allowed || allowed.includes(c.type))
  const missing = value !== '' && loaded && !choices.some(c => c.name === value)
  const style: React.CSSProperties = { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '6px 10px', outline: 'none', fontFamily: 'var(--font)', flex: 1, minWidth: 0, cursor: 'pointer' }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <select style={style} value={value} onChange={e => onChange(e.target.value)}>
          <option value="">{emptyLabel ?? (choices.length ? 'Choose a connection…' : 'No connections yet')}</option>
          {choices.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
          {missing && <option value={value}>{value} (not on this machine)</option>}
        </select>
        <button type="button" onClick={() => setShowConnectionsModal(true)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer', fontSize: 11, flexShrink: 0 }}>Manage…</button>
      </div>
      {missing && <div style={{ fontSize: 10, color: 'var(--warning)' }}>This pipeline uses a connection named "{value}" that isn't saved here. Create it under Connections.</div>}
    </div>
  )
}

function FileField({ value, accept, onChange }: { value: string; accept?: string; onChange: (v: string) => void }) {
  const showToast = useUiStore(s => s.showToast)
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''  // allow re-picking the same file later
    if (!file) return
    setUploading(true)
    try {
      const { path } = await api.uploadFile(file)
      onChange(path)
      showToast(`Uploaded ${file.name}`, 'success')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      showToast(msg, 'error')
    } finally {
      setUploading(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text)', fontSize: 12, padding: '6px 10px', outline: 'none',
    fontFamily: 'var(--mono)', flex: 1, minWidth: 0, transition: 'border-color 0.15s',
  }
  const buttonStyle: React.CSSProperties = {
    padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)',
    background: uploading ? 'var(--card2)' : 'var(--card)', color: 'var(--text)',
    cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 11, fontWeight: 500,
    flexShrink: 0, whiteSpace: 'nowrap',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          style={inputStyle}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="Path or click Browse…"
        />
        <button
          type="button"
          style={buttonStyle}
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? 'Uploading…' : 'Browse…'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          style={{ display: 'none' }}
          onChange={onPick}
        />
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
        Picked files are uploaded to <code style={{ fontFamily: 'var(--mono)' }}>~/.athena/uploads/</code>. You can also paste a path that already exists on this machine.
      </div>
    </div>
  )
}

function HpParamsField({ value, onChange }: { value: HpParam[]; onChange: (v: HpParam[]) => void }) {
  const update = (i: number, field: 'key' | 'values', v: string) =>
    onChange(value.map((r, idx) => idx === i ? { ...r, [field]: v } : r))
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i))
  const add = () => onChange([...value, { key: '', values: '' }])

  const cellInput: React.CSSProperties = {
    background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 5,
    color: 'var(--text)', fontSize: 11, padding: '5px 7px', outline: 'none',
    fontFamily: 'var(--mono)', flex: 1, minWidth: 0,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {value.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 22px', gap: 4 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', paddingLeft: 2 }}>Parameter</span>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', paddingLeft: 2 }}>Values</span>
          <span />
        </div>
      )}
      {value.map((row, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 22px', gap: 4, alignItems: 'center' }}>
          <input style={cellInput} value={row.key} placeholder="n_estimators" onChange={e => update(i, 'key', e.target.value)} />
          <input style={cellInput} value={row.values} placeholder="1,2,5 or 1-50" onChange={e => update(i, 'values', e.target.value)} />
          <button type="button" onClick={() => remove(i)} style={{ padding: '3px 5px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13, lineHeight: 1 }}>×</button>
        </div>
      ))}
      <button type="button" onClick={add} style={{ padding: '5px 10px', background: 'transparent', border: '1px dashed var(--border2)', borderRadius: 5, color: 'var(--text-muted)', cursor: 'pointer', fontSize: 11, textAlign: 'left' }}>+ Add parameter</button>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
        Values: <code style={{ fontFamily: 'var(--mono)' }}>1,2,10</code> · <code style={{ fontFamily: 'var(--mono)' }}>1-50</code> · <code style={{ fontFamily: 'var(--mono)' }}>1-50,100</code>
      </div>
    </div>
  )
}

function ColMapField({ value, onChange }: { value: HpParam[]; onChange: (v: HpParam[]) => void }) {
  const update = (i: number, field: 'key' | 'values', v: string) =>
    onChange(value.map((r, idx) => idx === i ? { ...r, [field]: v } : r))
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i))
  const add = () => onChange([...value, { key: '', values: '' }])

  const cellInput: React.CSSProperties = {
    background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 5,
    color: 'var(--text)', fontSize: 11, padding: '5px 7px', outline: 'none',
    fontFamily: 'var(--mono)', flex: 1, minWidth: 0,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {value.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 22px', gap: 4 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', paddingLeft: 2 }}>Existing Name</span>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', paddingLeft: 2 }}>New Name</span>
          <span />
        </div>
      )}
      {value.map((row, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 22px', gap: 4, alignItems: 'center' }}>
          <input style={cellInput} value={row.key} placeholder="old_col" onChange={e => update(i, 'key', e.target.value)} />
          <input style={cellInput} value={row.values} placeholder="new_col" onChange={e => update(i, 'values', e.target.value)} />
          <button type="button" onClick={() => remove(i)} style={{ padding: '3px 5px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13, lineHeight: 1 }}>×</button>
        </div>
      ))}
      <button type="button" onClick={add} style={{ padding: '5px 10px', background: 'transparent', border: '1px dashed var(--border2)', borderRadius: 5, color: 'var(--text-muted)', cursor: 'pointer', fontSize: 11, textAlign: 'left' }}>+ Add rename</button>
    </div>
  )
}

function PreviewTab({ preview }: { preview?: ArtifactPreview }) {
  if (!preview) {
    return <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.7 }}>Run the pipeline to see a preview.</div>
  }

  if (preview.kind === 'dataframe' && preview.columns && preview.rows) {
    return (
      <div style={{ padding: 12, overflowX: 'auto' }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, display: 'flex', gap: 12 }}>
          <span><strong style={{ color: 'var(--text)' }}>{preview.shape?.[0] ?? preview.rows.length}</strong> rows</span>
          <span><strong style={{ color: 'var(--text)' }}>{preview.shape?.[1] ?? preview.columns.length}</strong> cols</span>
          <span style={{ marginLeft: 'auto', color: 'var(--success)' }}>● Live</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr>{preview.columns.map(c => <th key={c} style={{ textAlign: 'left', padding: '5px 8px', background: 'var(--card2)', color: 'var(--text-dim)', fontWeight: 600, borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap', fontSize: 10.5 }}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--card)' }}>
                  {(row as unknown[]).map((cell, j) => <td key={j} style={{ padding: '4px 8px', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)', fontFamily: 'var(--mono)', fontSize: 11 }}>{String(cell)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-muted)' }}>Showing {preview.rows.length} of {preview.shape?.[0] ?? preview.rows.length} rows</div>
      </div>
    )
  }

  if (preview.kind === 'plot' && preview.data) {
    return (
      <div style={{ padding: 12, textAlign: 'center' }}>
        <img src={`data:image/png;base64,${preview.data}`} alt="Plot" style={{ maxWidth: '100%', borderRadius: 8 }} />
        <a href={`data:image/png;base64,${preview.data}`} download="plot.png" style={{ display: 'block', marginTop: 8, fontSize: 11, color: 'var(--accent)', cursor: 'pointer' }}>↓ Download PNG</a>
      </div>
    )
  }

  if (preview.kind === 'metrics' && preview.values) {
    return (
      <div style={{ padding: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {Object.entries(preview.values).map(([k, v]) => (
            <div key={k} style={{ background: 'var(--card)', borderRadius: 8, padding: '10px 12px', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', lineHeight: 1.2 }}>{typeof v === 'number' ? v.toFixed(4) : v}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (preview.kind === 'model' && preview.summary) {
    return <div style={{ padding: 16, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.6 }}>{preview.summary}</div>
  }

  if (preview.kind === 'text' && preview.text) {
    return (
      <div style={{ padding: 16 }}>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.6, marginBottom: preview.download_content ? 10 : 0 }}>{preview.text}</div>
        {preview.download_content && preview.download_filename && (
          <a
            href={`data:text/html;base64,${preview.download_content}`}
            download={preview.download_filename}
            style={{ display: 'inline-block', fontSize: 11, color: 'var(--accent)', cursor: 'pointer', textDecoration: 'none', padding: '5px 10px', border: '1px solid var(--accent)40', borderRadius: 5, background: 'var(--accent)10' }}
          >
            ↓ Download {preview.download_filename}
          </a>
        )}
      </div>
    )
  }

  if (preview.kind === 'dataframe_info' && preview.info_columns) {
    return <DataframeInfoView preview={preview} />
  }

  return null
}

function DataframeInfoView({ preview }: { preview: ArtifactPreview }) {
  const cols = preview.info_columns ?? []
  const thStyle: React.CSSProperties = {
    padding: '5px 8px', background: 'var(--card2)', color: 'var(--text-dim)',
    fontWeight: 600, borderBottom: '1px solid var(--border)', fontSize: 10,
    textAlign: 'left', whiteSpace: 'nowrap', position: 'sticky', top: 0,
  }
  const tdStyle: React.CSSProperties = {
    padding: '4px 8px', borderBottom: '1px solid var(--border)',
    fontSize: 10.5, color: 'var(--text-dim)', whiteSpace: 'nowrap',
    fontFamily: 'var(--mono)',
  }

  return (
    <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <SummaryCard label="Shape" value={`${(preview.shape?.[0] ?? 0).toLocaleString()} × ${preview.shape?.[1] ?? 0}`} />
        <SummaryCard label="Duplicates" value={(preview.duplicates ?? 0).toLocaleString()} />
        <SummaryCard label="Missing Cells" value={(preview.total_missing ?? 0).toLocaleString()} />
        <SummaryCard label="Missing %" value={`${preview.missing_pct?.toFixed(1) ?? '0'}%`} />
      </div>

      {/* Column table */}
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Columns ({cols.length})
      </div>
      <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 400, border: '1px solid var(--border)', borderRadius: 6 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10.5 }}>
          <thead>
            <tr>
              <th style={thStyle}>Column</th>
              <th style={thStyle}>Type</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Missing</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Unique</th>
              <th style={thStyle}>Stats</th>
            </tr>
          </thead>
          <tbody>
            {cols.map((col: ColumnInfo, i: number) => (
              <tr key={col.name} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--card)' }}>
                <td style={{ ...tdStyle, fontWeight: 600, color: 'var(--text)', maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis' }} title={col.name}>{col.name}</td>
                <td style={{ ...tdStyle, color: 'var(--accent)', fontSize: 10 }}>{col.dtype}</td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {col.missing > 0
                    ? <span style={{ color: 'var(--warning)' }}>{col.missing} <span style={{ opacity: 0.7 }}>({col.missing_pct.toFixed(1)}%)</span></span>
                    : <span style={{ color: 'var(--success)' }}>0</span>
                  }
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>{col.unique.toLocaleString()}</td>
                <td style={{ ...tdStyle, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', fontSize: 10 }}>
                  {col.top_values
                    ? <span style={{ color: 'var(--text-muted)' }}>{col.top_values.slice(0, 4).join(', ')}{col.top_values.length > 4 ? '…' : ''}</span>
                    : col.min !== undefined
                      ? <span>
                          <span style={{ color: 'var(--text-muted)' }}>μ </span>{col.mean?.toFixed(3)}
                          <span style={{ color: 'var(--text-muted)' }}> σ </span>{col.std?.toFixed(3)}
                          <span style={{ color: 'var(--text-muted)' }}> [{col.min?.toFixed(2)}, {col.max?.toFixed(2)}]</span>
                        </span>
                      : <span style={{ color: 'var(--text-muted)' }}>all missing</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: 'var(--card)', borderRadius: 7, padding: '8px 10px', border: '1px solid var(--border)' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', lineHeight: 1.2, fontFamily: 'var(--mono)' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
    </div>
  )
}

function LogsTab({ logs }: { logs: LogEntry[] }) {
  const levelColors: Record<string, string> = { info: 'var(--text-muted)', warn: 'var(--warning)', error: 'var(--error)', success: 'var(--success)', debug: 'var(--text-muted)' }

  if (logs.length === 0) {
    return <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 12 }}>No logs yet. Run the pipeline.</div>
  }

  return (
    <div style={{ padding: '8px 0', display: 'flex', flexDirection: 'column', gap: 1 }}>
      {logs.map((l, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 14px', fontSize: 11, background: i % 2 === 0 ? 'transparent' : 'var(--card)' }}>
          <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--mono)', flexShrink: 0 }}>{l.ts ? l.ts.slice(11, 19) : ''}</span>
          <span style={{ color: levelColors[l.level] ?? 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', fontSize: 9.5, flexShrink: 0, paddingTop: 1 }}>{l.level}</span>
          <span style={{ color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>{l.msg}</span>
        </div>
      ))}
    </div>
  )
}

function MetricsTab({ metrics }: { metrics: Record<string, number> }) {
  if (Object.keys(metrics).length === 0) {
    return <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.7 }}>Run the pipeline to see performance metrics.</div>
  }

  return (
    <div style={{ padding: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Metrics</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {Object.entries(metrics).map(([k, v]) => (
          <div key={k} style={{ background: 'var(--card)', borderRadius: 8, padding: '10px 12px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--text)', lineHeight: 1.2 }}>
              {typeof v === 'number' ? formatMetric(k, v) : v}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
