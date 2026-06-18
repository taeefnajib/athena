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
        set({ toast: { msg, type } })
        setTimeout(() => set({ toast: null }), type === 'error' ? 0 : 2800)
      },
      clearToast: () => set({ toast: null }),
    }),
    { name: 'athena-ui', partialize: (s) => ({ theme: s.theme }) }
  )
)
