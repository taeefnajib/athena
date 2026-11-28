import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UiState {
  theme: 'light' | 'dark' | 'system'
  showExportModal: boolean
  showTemplatesModal: boolean
  showSaveModal: boolean
  showLoadModal: boolean
  showConnectionsModal: boolean
  showTrackingModal: boolean
  showRunsModal: boolean
  inspectorTab: 'settings' | 'preview' | 'logs' | 'metrics' | 'code'
  profileTarget: { nodeId: string; port: number } | null
  /** Nodes a pending "Run from here" would execute, highlighted on the canvas while hovering the button. */
  runPreview: string[] | null
  /** Bumped when the subflow library changes, so the sidebar list refetches. */
  subflowLibraryVersion: number
  showCompareModal: boolean
  showServingModal: boolean
  /** A model output to package (set by Deploy in the inspector). */
  deployTarget: { nodeId: string; port: number } | null
  /** Changes vs another version, marked on the canvas until cleared. */
  diffMarks: { against: string; marks: Record<string, 'added' | 'changed'>; removed: number } | null
  toast: { msg: string; type: 'info' | 'success' | 'error' | 'warn' } | null

  setTheme: (theme: UiState['theme']) => void
  setShowExportModal: (show: boolean) => void
  setShowTemplatesModal: (show: boolean) => void
  setShowSaveModal: (show: boolean) => void
  setShowLoadModal: (show: boolean) => void
  setShowConnectionsModal: (show: boolean) => void
  setShowTrackingModal: (show: boolean) => void
  setShowRunsModal: (show: boolean) => void
  setInspectorTab: (tab: UiState['inspectorTab']) => void
  setProfileTarget: (target: UiState['profileTarget']) => void
  setRunPreview: (ids: string[] | null) => void
  bumpSubflowLibrary: () => void
  setShowCompareModal: (show: boolean) => void
  setShowServingModal: (show: boolean) => void
  setDeployTarget: (target: UiState['deployTarget']) => void
  setDiffMarks: (marks: UiState['diffMarks']) => void
  showToast: (msg: string, type?: 'info' | 'success' | 'error' | 'warn') => void
  clearToast: () => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: 'dark',
      showExportModal: false,
      showTemplatesModal: false,
      showSaveModal: false,
      showLoadModal: false,
      showConnectionsModal: false,
      showTrackingModal: false,
      showRunsModal: false,
      inspectorTab: 'settings',
      profileTarget: null,
      runPreview: null,
      subflowLibraryVersion: 0,
      showCompareModal: false,
      showServingModal: false,
      deployTarget: null,
      diffMarks: null,
      toast: null,

      setTheme: (theme) => set({ theme }),
      setShowExportModal: (show) => set({ showExportModal: show }),
      setShowTemplatesModal: (show) => set({ showTemplatesModal: show }),
      setShowSaveModal: (show) => set({ showSaveModal: show }),
      setShowLoadModal: (show) => set({ showLoadModal: show }),
      setShowConnectionsModal: (show) => set({ showConnectionsModal: show }),
      setShowTrackingModal: (show) => set({ showTrackingModal: show }),
      setShowRunsModal: (show) => set({ showRunsModal: show }),
      setInspectorTab: (tab) => set({ inspectorTab: tab }),
      setProfileTarget: (target) => set({ profileTarget: target }),
      setRunPreview: (ids) => set({ runPreview: ids }),
      bumpSubflowLibrary: () => set(s => ({ subflowLibraryVersion: s.subflowLibraryVersion + 1 })),
      setShowCompareModal: (show) => set({ showCompareModal: show }),
      setShowServingModal: (show) => set(show ? { showServingModal: true } : { showServingModal: false, deployTarget: null }),
      setDeployTarget: (target) => set({ deployTarget: target, showServingModal: target !== null }),
      setDiffMarks: (marks) => set({ diffMarks: marks }),
      showToast: (msg, type = 'info') => {
        const toast = { msg, type }
        set({ toast })
        // Errors stay until clicked (frontend/CLAUDE.md §10); others fade after 2.8 s.
        // Only clear this toast: a newer one must not be wiped by an older timer.
        if (type !== 'error') setTimeout(() => set(s => (s.toast === toast ? { toast: null } : {})), 2800)
      },
      clearToast: () => set({ toast: null }),
    }),
    { name: 'athena-ui', partialize: (s) => ({ theme: s.theme }) }
  )
)
