import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UiState {
  theme: 'light' | 'dark' | 'system'
  showExportModal: boolean
  showTemplatesModal: boolean
  showSaveModal: boolean
  showLoadModal: boolean
  inspectorTab: 'settings' | 'preview' | 'logs' | 'metrics'
  toast: { msg: string; type: 'info' | 'success' | 'error' | 'warn' } | null

  setTheme: (theme: UiState['theme']) => void
  setShowExportModal: (show: boolean) => void
  setShowTemplatesModal: (show: boolean) => void
  setShowSaveModal: (show: boolean) => void
  setShowLoadModal: (show: boolean) => void
  setInspectorTab: (tab: UiState['inspectorTab']) => void
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
      inspectorTab: 'settings',
      toast: null,

      setTheme: (theme) => set({ theme }),
      setShowExportModal: (show) => set({ showExportModal: show }),
      setShowTemplatesModal: (show) => set({ showTemplatesModal: show }),
      setShowSaveModal: (show) => set({ showSaveModal: show }),
      setShowLoadModal: (show) => set({ showLoadModal: show }),
      setInspectorTab: (tab) => set({ inspectorTab: tab }),
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
