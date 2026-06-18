import type { LogEntry, NodeFinishEvent } from '../types/pipeline'

interface WsCallbacks {
  onNodeStart: (e: { node_id: string }) => void
  onNodeLog: (e: { node_id: string; level: LogEntry['level']; msg: string; ts: string }) => void
  onNodeFinish: (e: NodeFinishEvent) => void
  onRunFinish: (e: { status: string }) => void
  onError: () => void
}

export function openRunWS(runId: string, callbacks: WsCallbacks): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/runs/${runId}`)

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data as string)
    switch (data.type) {
      case 'node_start':  callbacks.onNodeStart(data);  break
      case 'node_log':    callbacks.onNodeLog(data);    break
      case 'node_finish': callbacks.onNodeFinish(data); break
      case 'run_finish':  callbacks.onRunFinish(data);  break
    }
  }
  ws.onerror = callbacks.onError
  return ws
}
