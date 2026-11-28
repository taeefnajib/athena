import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useExecutionStore } from '../store/executionStore'
import { useUiStore } from '../store/uiStore'
import { innerIds, subflowConfig } from '../lib/subflow'
import type { NodeStatus } from '../types/pipeline'

const STATUS_COLORS: Record<string, string> = { success: 'var(--success)', error: 'var(--error)', running: 'var(--running)', idle: 'transparent' }

/** The status of a subflow is its inner nodes' (the backend runs them as ``<subflow>.<inner>``): running while any
 *  runs, error if any failed, success once all succeeded. */
export function subflowStatus(states: Record<string, { status: NodeStatus } | undefined>, ids: string[]): NodeStatus {
  const s = ids.map(i => states[i]?.status ?? 'idle')
  if (s.includes('error')) return 'error'
  if (s.includes('running')) return 'running'
  if (s.length && s.every(x => x === 'success')) return 'success'
  if (s.some(x => x === 'success')) return 'running'  // part-way through
  return 'idle'
}

/** A subflow on the canvas: its name, size and the ports its boundary exposes. Double-click selects it like any node. */
export const SubflowNode = memo(function SubflowNode({ id, data, selected }: NodeProps) {
  const config = (data as { config: Record<string, unknown> }).config
  const sf = subflowConfig(config)
  const ids = innerIds(id, config)
  const status = useExecutionStore(s => subflowStatus(s.nodeStates, ids))
  const cached = useExecutionStore(s => ids.length > 0 && ids.every(i => s.nodeStates[i]?.cached))
  const willRun = useUiStore(s => s.runPreview?.includes(id) ?? false)
  const diffMark = useUiStore(s => s.diffMarks?.marks[id])
  const maxPorts = Math.max(sf.inputs.length, sf.outputs.length, 1)

  return (
    <div data-nodeid={id} className={status === 'running' ? 'node-running' : ''} style={{
      width: 200, background: 'var(--card)', borderRadius: 10, position: 'relative', userSelect: 'none',
      border: `1px solid ${selected ? 'var(--accent)' : 'var(--border2)'}`,
      boxShadow: willRun ? '0 0 0 2px var(--accent), var(--shadow)' : selected ? '0 0 0 2.5px var(--accent-glow), var(--shadow)'
        : '3px 3px 0 -1px var(--card), 3px 3px 0 0 var(--border2), var(--shadow)',  // a stacked-card edge: it holds several nodes
    }}>
      {status !== 'idle' && <div style={{ position: 'absolute', top: 0, left: 10, right: 10, height: 2, background: STATUS_COLORS[status], borderRadius: '0 0 4px 4px', zIndex: 3 }} />}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '8px 10px 2px', cursor: 'grab' }}>
        <div style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--cat-subflow)', flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sf.name}</span>
        {diffMark && (
          <span title={`${diffMark === 'added' ? 'Added' : 'Changed'} since the version you compared with`}
                style={{ fontSize: 9, fontWeight: 600, color: 'var(--text)', background: 'var(--card2)', border: '1px solid var(--accent)', borderRadius: 99, padding: '0 5px', lineHeight: '13px', flexShrink: 0 }}>
            {diffMark === 'added' ? 'new' : 'changed'}
          </span>
        )}
        {cached && status === 'success' && (
          <span title="Every node inside was reused from an earlier run" style={{ fontSize: 9, color: 'var(--text-muted)', border: '1px solid var(--border2)', borderRadius: 99, padding: '0 5px', lineHeight: '13px' }}>cached</span>
        )}
        <div style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: status === 'idle' ? 'transparent' : STATUS_COLORS[status], border: status === 'idle' ? '1.5px solid var(--border2)' : 'none' }} />
      </div>
      <div style={{ padding: '0 10px 6px 25px', fontSize: 10, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>
        Subflow · {ids.length} node{ids.length === 1 ? '' : 's'}
      </div>
      <div style={{ padding: '4px 0', minHeight: 26 }}>
        {Array.from({ length: maxPorts }).map((_, i) => {
          const inp = sf.inputs[i], out = sf.outputs[i]
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', height: 26, position: 'relative' }}>
              {inp && (<>
                <Handle type="target" position={Position.Left} id={`input-${i}`} style={{ top: '50%', transform: 'translateY(-50%)', position: 'absolute', left: -7 }} />
                <span style={{ marginLeft: 14, fontSize: 10.5, color: 'var(--text-muted)', maxWidth: 85, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={inp.name}>{inp.name}</span>
              </>)}
              {out && (<>
                <span style={{ marginLeft: 'auto', marginRight: 14, fontSize: 10.5, color: 'var(--text-muted)', maxWidth: 85, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={out.name}>{out.name}</span>
                <Handle type="source" position={Position.Right} id={`output-${i}`} style={{ top: '50%', transform: 'translateY(-50%)', position: 'absolute', right: -7 }} />
              </>)}
            </div>
          )
        })}
      </div>
    </div>
  )
})
