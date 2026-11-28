import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { NODE_REGISTRY, CATEGORY_META } from '../registry/nodeRegistry'
import { useExecutionStore } from '../store/executionStore'
import { useUiStore } from '../store/uiStore'

export interface AthenaNodeData extends Record<string, unknown> {
  nodeType: string
  config: Record<string, unknown>
}

const STATUS_COLORS: Record<string, string> = {
  success: 'var(--success)',
  error: 'var(--error)',
  running: 'var(--running)',
  idle: 'transparent',
}

export const BaseNode = memo(function BaseNode({ id, data, selected }: NodeProps) {
  const nodeType = data.nodeType as string
  const spec = NODE_REGISTRY[nodeType]
  const nodeState = useExecutionStore(s => s.nodeStates[id])
  const status = nodeState?.status ?? 'idle'
  const willRun = useUiStore(s => s.runPreview?.includes(id) ?? false)
  const diffMark = useUiStore(s => s.diffMarks?.marks[id])

  if (!spec) {
    return (
      <div style={{ background: 'var(--card)', border: '1px solid var(--error)', borderRadius: 10, padding: 8, width: 200, fontSize: 11, color: 'var(--error)' }}>
        Unknown node: {nodeType}
      </div>
    )
  }

  const catMeta = CATEGORY_META[spec.category]
  const isRunning = status === 'running'
  const statusColor = STATUS_COLORS[status]

  const maxPorts = Math.max(spec.inputs.length, spec.outputs.length, 1)

  return (
    <div
      data-nodeid={id}
      className={isRunning ? 'node-running' : ''}
      style={{
        width: 200,
        background: 'var(--card)',
        border: `1px solid ${selected ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 10,
        boxShadow: willRun ? '0 0 0 2px var(--accent), var(--shadow)' : selected ? '0 0 0 2.5px var(--accent-glow), var(--shadow)' : 'var(--shadow)',
        userSelect: 'none',
        transition: 'border-color 0.15s, box-shadow 0.15s',
        position: 'relative',
      }}
    >
      {/* Status bar */}
      {status !== 'idle' && (
        <div style={{
          position: 'absolute', top: 0, left: 10, right: 10, height: 2,
          background: statusColor, borderRadius: '0 0 4px 4px', zIndex: 3,
          transition: 'background 0.3s',
        }} />
      )}

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 7, padding: '8px 10px',
        borderBottom: '1px solid var(--border)', cursor: 'grab',
        borderRadius: '9px 9px 0 0',
        background: selected ? `${catMeta.color}15` : 'transparent',
        transition: 'background 0.15s',
      }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: catMeta.color, flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', flex: 1, lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {spec.label}
        </span>
        {diffMark && (
          <span title={`${diffMark === 'added' ? 'Added' : 'Changed'} since the version you compared with`}
                style={{ fontSize: 9, fontWeight: 600, color: 'var(--text)', background: 'var(--card2)', border: '1px solid var(--accent)', borderRadius: 99, padding: '0 5px', lineHeight: '13px', flexShrink: 0 }}>
            {diffMark === 'added' ? 'new' : 'changed'}
          </span>
        )}
        {status === 'success' && nodeState?.cached && (
          <span title="Reused from an earlier run (nothing it depends on changed)"
                style={{ fontSize: 9, color: 'var(--text-muted)', border: '1px solid var(--border2)', borderRadius: 99, padding: '0 5px', lineHeight: '13px', flexShrink: 0 }}>
            cached
          </span>
        )}
        <div style={{
          width: 7, height: 7, borderRadius: '50%',
          background: status === 'idle' ? 'transparent' : statusColor,
          border: status === 'idle' ? '1.5px solid var(--border2)' : 'none',
          transition: 'background 0.3s', flexShrink: 0,
        }} />
      </div>

      {/* Ports */}
      <div style={{ padding: '4px 0', minHeight: 26 }}>
        {Array.from({ length: maxPorts }).map((_, i) => {
          const inp = spec.inputs[i]
          const out = spec.outputs[i]
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', height: 26, position: 'relative' }}>
              {inp && (
                <>
                  <Handle
                    type="target"
                    position={Position.Left}
                    id={`input-${i}`}
                    style={{ top: '50%', transform: 'translateY(-50%)', position: 'absolute', left: -7 }}
                  />
                  <span style={{ marginLeft: 14, fontSize: 10.5, color: 'var(--text-muted)' }}>{inp.name}</span>
                </>
              )}
              {out && (
                <>
                  <span style={{ marginLeft: 'auto', marginRight: 14, fontSize: 10.5, color: 'var(--text-muted)' }}>{out.name}</span>
                  <Handle
                    type="source"
                    position={Position.Right}
                    id={`output-${i}`}
                    style={{ top: '50%', transform: 'translateY(-50%)', position: 'absolute', right: -7 }}
                  />
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
})
