import { useEffect, useRef } from 'react'
import { usePipelineStore } from '../store/pipelineStore'
import { useUiStore } from '../store/uiStore'
import { api } from '../lib/api'
import { fromPipelineSpec } from '../lib/serialize'

export function useAutosave() {
  const { isDirty, toPipelineSpec, loadPipeline } = usePipelineStore()
  const { showToast } = useUiStore()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const recoveryChecked = useRef(false)

  // On first mount, ask the user whether to recover any autosaved pipeline
  useEffect(() => {
    if (recoveryChecked.current) return
    recoveryChecked.current = true

    api.getLatestAutosave().then(data => {
      if (!data?.spec) return
      const { nodes, edges } = fromPipelineSpec(data.spec)
      if (nodes.length === 0) return

      const current = usePipelineStore.getState()
      const sameStructure =
        nodes.length === current.nodes.length &&
        nodes.every((n, i) => n.id === current.nodes[i]?.id && n.type === current.nodes[i]?.type)
      if (sameStructure) return

      const ok = window.confirm(
        `Unsaved work was found from a previous session ` +
        `(${nodes.length} node${nodes.length === 1 ? '' : 's'}). Recover it?\n\n` +
        `Click OK to load, or Cancel to start fresh with the default pipeline.`
      )
      if (ok) {
        loadPipeline(nodes, edges)
        showToast('Pipeline recovered from autosave', 'success')
      }
    }).catch(() => { /* no autosave, that's fine */ })
  }, [loadPipeline, showToast])

  // Autosave every 10s when dirty
  useEffect(() => {
    if (!isDirty) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      api.autosave(toPipelineSpec()).catch(() => { /* silent */ })
    }, 10_000)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [isDirty, toPipelineSpec])
}
