import { useEffect, useRef } from 'react'
import { usePipelineStore } from '../store/pipelineStore'
import { useUiStore } from '../store/uiStore'
import { useExecutionStore } from '../store/executionStore'

interface ClipboardNode {
  type: string
  config: Record<string, unknown>
  pastePosition: { x: number; y: number }
}

export function useKeyboardShortcuts(onRun: () => void, onStop: () => void) {
  const { undo, redo, removeNode, removeEdge, addNode, selectedNodeId, selectedEdgeId, setSelectedNode, setSelectedEdge } = usePipelineStore()
  const { setShowSaveModal } = useUiStore()
  const status = useExecutionStore(s => s.status)

  const clipboard = useRef<ClipboardNode | null>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      const ctrl = e.metaKey || e.ctrlKey

      if (ctrl && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return }
      if (ctrl && (e.key === 'y' || (e.shiftKey && e.key === 'z'))) { e.preventDefault(); redo(); return }
      if (ctrl && e.key === 's') { e.preventDefault(); setShowSaveModal(true); return }
      if (ctrl && e.key === 'Enter') {
        e.preventDefault()
        if (status === 'running') onStop(); else onRun()
        return
      }
      if (ctrl && e.key === 'c') {
        const state = usePipelineStore.getState()
        const node = state.nodes.find(n => n.id === state.selectedNodeId)
        if (node) {
          e.preventDefault()
          clipboard.current = {
            type: node.type,
            config: { ...node.config },
            pastePosition: { x: node.position.x + 40, y: node.position.y + 40 },
          }
        }
        return
      }
      if (ctrl && e.key === 'v') {
        if (!clipboard.current) return
        e.preventDefault()
        const { type, config, pastePosition } = clipboard.current
        addNode(type, pastePosition, config)
        clipboard.current = { ...clipboard.current, pastePosition: { x: pastePosition.x + 40, y: pastePosition.y + 40 } }
        return
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedEdgeId) { e.preventDefault(); removeEdge(selectedEdgeId); return }
        if (selectedNodeId) { e.preventDefault(); removeNode(selectedNodeId); return }
      }
      if (e.key === 'Escape') { setSelectedNode(null); setSelectedEdge(null) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo, removeNode, removeEdge, addNode, selectedNodeId, selectedEdgeId, setSelectedNode, setSelectedEdge, setShowSaveModal, status, onRun, onStop])
}
