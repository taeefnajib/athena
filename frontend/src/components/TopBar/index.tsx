import { useState } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { trackingOf } from '../../types/pipeline'

interface TopBarProps {
  onRun: () => void
  onStop: () => void
}

function Btn({ children, onClick, disabled, primary, title }: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  primary?: boolean
  title?: string
}) {
  const [hov, setHov] = useState(false)
  return (
    <button
      title={title}
      onClick={disabled ? undefined : onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 5,
        padding: '5px 11px', borderRadius: 6, border: '1px solid',
        fontSize: 12, fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
        fontFamily: 'var(--font)', lineHeight: 1, transition: 'all 0.15s',
        background: primary
          ? (hov && !disabled ? 'oklch(74% 0.22 225)' : 'var(--accent)')
          : (hov && !disabled ? 'var(--card2)' : 'var(--card)'),
        color: primary ? 'white' : (disabled ? 'var(--text-muted)' : 'var(--text)'),
        borderColor: primary ? 'transparent' : (disabled ? 'var(--border)' : hov ? 'var(--border2)' : 'var(--border)'),
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {children}
    </button>
  )
}

const Divider = () => <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 4px', flexShrink: 0 }} />

const STATUS_CONFIG = {
  idle:      { color: 'var(--text-muted)', label: 'Idle',      dot: 'var(--text-muted)' },
  running:   { color: 'var(--running)',    label: 'Running…',  dot: 'var(--running)' },
  completed: { color: 'var(--success)',    label: 'Completed', dot: 'var(--success)' },
  error:     { color: 'var(--error)',      label: 'Error',     dot: 'var(--error)' },
}

export function TopBar({ onRun, onStop }: TopBarProps) {
  const { nodes, edges, undo, redo, historyIndex, history } = usePipelineStore()
  const status = useExecutionStore(s => s.status)
  const { theme, setTheme, setShowExportModal, setShowTemplatesModal, setShowSaveModal, setShowLoadModal, setShowConnectionsModal, setShowTrackingModal, setShowRunsModal, setShowCompareModal, setShowServingModal } = useUiStore()
  const tracking = trackingOf(usePipelineStore(s => s.meta))
  const sc = STATUS_CONFIG[status] ?? STATUS_CONFIG.idle

  const canUndo = historyIndex > 0
  const canRedo = historyIndex < history.length - 1

  return (
    <div style={{
      height: 48, flexShrink: 0,
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '0 14px',
      background: 'var(--panel)',
      borderBottom: '1px solid var(--border)',
      zIndex: 100,
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 8 }}>
        <div style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <polygon points="7,1 13,4.5 13,9.5 7,13 1,9.5 1,4.5" stroke="white" strokeWidth="1.5" fill="none"/>
            <circle cx="7" cy="7" r="2" fill="white"/>
          </svg>
        </div>
        <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)' }}>Athena</span>
      </div>

      <Divider />

      <Btn onClick={onRun} disabled={status === 'running'} primary>
        {status === 'running' ? <span className="spin" style={{ display: 'inline-block' }}>↻</span> : '▶'} Run
      </Btn>
      <Btn onClick={onStop} disabled={status !== 'running'}>⏹ Stop</Btn>

      <Divider />

      <Btn onClick={undo} disabled={!canUndo} title="Undo (⌘Z)">↩</Btn>
      <Btn onClick={redo} disabled={!canRedo} title="Redo (⌘⇧Z)">↪</Btn>

      <Divider />

      <Btn onClick={() => setShowSaveModal(true)}>Save</Btn>
      <Btn onClick={() => setShowLoadModal(true)}>Load</Btn>
      <Btn onClick={() => setShowCompareModal(true)} title="Compare this pipeline with a saved version">Compare</Btn>
      <Btn onClick={() => setShowTemplatesModal(true)}>Templates</Btn>
      <Btn onClick={() => setShowExportModal(true)}>Export Code</Btn>

      <Divider />

      <Btn onClick={() => setShowConnectionsModal(true)} title="Databases and other external systems">Connections</Btn>
      <Btn onClick={() => setShowTrackingModal(true)} title="Log runs to MLflow">
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: tracking.enabled ? 'var(--success)' : 'var(--text-muted)' }} />
        {tracking.enabled ? 'Tracking on' : 'Tracking off'}
      </Btn>
      <Btn onClick={() => setShowRunsModal(true)} title="Run history and comparison">Runs</Btn>
      <Btn onClick={() => setShowServingModal(true)} title="Packaged models and local prediction endpoints">Serving</Btn>

      <div style={{ flex: 1 }} />

      {/* Stats */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10, marginRight: 8 }}>
        <span>{nodes.length} nodes</span>
        <span>{edges.length} edges</span>
      </div>

      {/* Status pill */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: 'var(--card)', borderRadius: 99, border: '1px solid var(--border)' }}>
        <div style={{ width: 6, height: 6, borderRadius: '50%', background: sc.dot }} className={status === 'running' ? 'status-running' : ''} />
        <span style={{ fontSize: 11, fontWeight: 500, color: sc.color }}>{sc.label}</span>
      </div>

      <Divider />

      <button
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', cursor: 'pointer', padding: '5px 8px', fontSize: 14, lineHeight: 1 }}
        title="Toggle theme"
      >
        {theme === 'dark' ? '☀' : '◑'}
      </button>
    </div>
  )
}
