import { useRef, useCallback } from 'react'
import { usePipelineStore } from '../store/pipelineStore'
import { useExecutionStore } from '../store/executionStore'
import { useUiStore } from '../store/uiStore'
import { api, ApiError } from '../lib/api'
import { openRunWS } from '../lib/ws'
import { hasCycle } from '../lib/dag'

export function useRunPipeline() {
  const wsRef = useRef<WebSocket | null>(null)
  const { toPipelineSpec, nodes, edges, resetAllNodeStatuses, setNodeStatus } = usePipelineStore()
  const exec = useExecutionStore()
  const { showToast } = useUiStore()

  /** Run the pipeline, or with ``startFrom`` only those nodes and their descendants (ancestors come from the cache). */
  const run = useCallback(async (startFrom?: unknown) => {
    if (exec.status === 'running') return
    const from = Array.isArray(startFrom) ? (startFrom as string[]) : undefined  // a click event isn't a selection

    // Client-side cycle check
    if (hasCycle(nodes, edges)) {
      showToast('Pipeline contains a cycle — fix it before running', 'error')
      return
    }

    const spec = toPipelineSpec()
    resetAllNodeStatuses()
    exec.reset()
    exec.setStatus('running')

    try {
      let runResp: { run_id: string }
      try {
        runResp = await api.runPipeline(spec, { startFrom: from })
      } catch (err) {
        // If a previous run leaked the active-run flag on the backend, recover
        // by resetting and retrying once.
        if (err instanceof ApiError && err.status === 409) {
          await api.resetRuns()
          runResp = await api.runPipeline(spec, { startFrom: from })
        } else {
          throw err
        }
      }
      const { run_id } = runResp
      exec.setRunId(run_id)

      const ws = openRunWS(run_id, {
        onNodeStart: (e) => {
          setNodeStatus(e.node_id, 'running')
          exec.markRunning(e.node_id)
        },
        onNodeLog: (e) => {
          exec.appendLog(e.node_id, { level: e.level as never, msg: e.msg, ts: e.ts })
        },
        onNodeFinish: (e) => {
          setNodeStatus(e.node_id, e.status)
          exec.markFinished(e.node_id, e)
        },
        onRunFinish: (e) => {
          exec.setStatus(e.status as 'completed' | 'error')
          wsRef.current?.close()
          wsRef.current = null
          if (e.status === 'completed') showToast('Pipeline completed successfully!', 'success')
          else if (e.status === 'error') showToast('Pipeline failed — check node errors', 'error')
        },
        onRunInfo: (e) => {
          if (e.tracking) exec.setTracking(e.tracking)
          if (e.message) showToast(e.message, 'info')
          if (e.warning) showToast(`Tracking: ${e.warning}`, 'warn')
        },
        onError: () => {
          exec.setStatus('error')
          showToast("Couldn't reach the backend. Is uvicorn running on :8000?", 'error')
        },
      })
      wsRef.current = ws
    } catch {
      exec.setStatus('error')
      showToast("Couldn't start pipeline — is the backend running?", 'error')
    }
  }, [exec, nodes, edges, toPipelineSpec, resetAllNodeStatuses, setNodeStatus, showToast])

  const stop = useCallback(async () => {
    const runId = exec.runId
    if (runId) await api.cancelRun(runId)
    wsRef.current?.close()
    wsRef.current = null
    exec.setStatus('idle')
    resetAllNodeStatuses()
    showToast('Pipeline stopped', 'warn')
  }, [exec, resetAllNodeStatuses, showToast])

  return { run, stop }
}
