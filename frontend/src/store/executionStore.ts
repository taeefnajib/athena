import { create } from 'zustand'
import type { ArtifactPreview, LogEntry, NodeFinishEvent, NodeStatus, TrackingInfo } from '../types/pipeline'

interface NodeRunState {
  status: NodeStatus
  error?: { message: string; traceback: string }
  duration_ms?: number
}

interface ExecutionState {
  runId: string | null
  status: 'idle' | 'running' | 'completed' | 'error'
  currentNodeId: string | null
  nodeStates: Record<string, NodeRunState>
  logs: Record<string, LogEntry[]>
  previews: Record<string, ArtifactPreview>
  metrics: Record<string, Record<string, number>>
  /** Set when the run is tracked (run_info event): which MLflow run it logged to. */
  tracking: TrackingInfo | null

  reset: () => void
  setTracking: (info: TrackingInfo) => void
  setStatus: (status: ExecutionState['status']) => void
  setRunId: (id: string) => void
  markRunning: (nodeId: string) => void
  markFinished: (nodeId: string, event: NodeFinishEvent) => void
  appendLog: (nodeId: string, entry: LogEntry) => void
}

export const useExecutionStore = create<ExecutionState>((set) => ({
  runId: null,
  status: 'idle',
  currentNodeId: null,
  nodeStates: {},
  logs: {},
  previews: {},
  metrics: {},
  tracking: null,
  setTracking: (info) => set({ tracking: info }),

  reset: () => set({
    runId: null, status: 'idle', currentNodeId: null,
    nodeStates: {}, logs: {}, previews: {}, metrics: {}, tracking: null,
  }),

  setStatus: (status) => set({ status }),
  setRunId: (id) => set({ runId: id }),

  markRunning: (nodeId) => set(s => ({
    currentNodeId: nodeId,
    nodeStates: { ...s.nodeStates, [nodeId]: { status: 'running' } },
  })),

  markFinished: (nodeId, event) => set(s => {
    const nodeState: NodeRunState = {
      status: event.status,
      error: event.error,
      duration_ms: event.duration_ms,
    }
    const updates: Partial<ExecutionState> = {
      currentNodeId: null,
      nodeStates: { ...s.nodeStates, [nodeId]: nodeState },
    }
    if (event.preview) updates.previews = { ...s.previews, [nodeId]: event.preview }
    if (event.metrics && Object.keys(event.metrics).length > 0) {
      updates.metrics = { ...s.metrics, [nodeId]: event.metrics }
    }
    return updates
  }),

  appendLog: (nodeId, entry) => set(s => ({
    logs: { ...s.logs, [nodeId]: [...(s.logs[nodeId] ?? []), entry] },
  })),
}))
