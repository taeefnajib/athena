import { usePipelineStore } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { withDescendants } from '../../lib/dag'

/** Re-run this node and everything downstream; upstream results come from the cache when unchanged.
 *  Hovering (or focusing) highlights exactly the nodes that will run, before anything runs. */
export function RunFromHere({ nodeId, onRunFrom }: { nodeId: string; onRunFrom: (nodeId: string) => void }) {
  const edges = usePipelineStore(s => s.edges)
  const running = useExecutionStore(s => s.status === 'running')
  const setRunPreview = useUiStore(s => s.setRunPreview)
  const affected = () => withDescendants(nodeId, edges)
  const hide = () => setRunPreview(null)
  return (
    <button
      disabled={running}
      onClick={() => { hide(); onRunFrom(nodeId) }}
      onMouseEnter={() => setRunPreview(affected())}
      onMouseLeave={hide}
      onFocus={() => setRunPreview(affected())}
      onBlur={hide}
      title="Re-run this node and the nodes after it. Unchanged nodes before it are taken from the cache."
      style={{
        marginLeft: 'auto', fontSize: 10.5, padding: '2px 8px', borderRadius: 5, border: '1px solid var(--border2)',
        background: 'var(--card)', color: running ? 'var(--text-muted)' : 'var(--text)', cursor: running ? 'default' : 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      ▶ Run from here
    </button>
  )
}
