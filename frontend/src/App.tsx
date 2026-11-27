import { ReactFlowProvider } from '@xyflow/react'
import { TopBar } from './components/TopBar'
import { LeftSidebar } from './components/LeftSidebar'
import { GraphCanvas } from './components/GraphCanvas'
import { RightSidebar } from './components/RightSidebar'
import { ExportModal } from './components/modals/ExportModal'
import { TemplatesModal } from './components/modals/TemplatesModal'
import { SaveModal } from './components/modals/SaveModal'
import { LoadModal } from './components/modals/LoadModal'
import { ConnectionsModal } from './components/modals/ConnectionsModal'
import { TrackingModal } from './components/modals/TrackingModal'
import { RunsModal } from './components/modals/RunsModal'
import { ProfileModal } from './components/modals/ProfileModal'
import { Toaster } from './components/ui/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useTheme } from './hooks/useTheme'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useAutosave } from './hooks/useAutosave'
import { useRunPipeline } from './hooks/useRunPipeline'
import { useUiStore } from './store/uiStore'

function AppInner() {
  const { run, stop } = useRunPipeline()
  const { showExportModal, showTemplatesModal, showSaveModal, showLoadModal, showConnectionsModal, showTrackingModal, showRunsModal, profileTarget } = useUiStore()

  useTheme()
  useKeyboardShortcuts(run, stop)
  useAutosave()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', overflow: 'hidden' }}>
      <TopBar onRun={run} onStop={stop} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <LeftSidebar />
        <GraphCanvas />
        <RightSidebar onRunFrom={(id: string) => run([id])} />
      </div>
      <Toaster />
      {showExportModal && <ExportModal />}
      {showTemplatesModal && <TemplatesModal />}
      {showSaveModal && <SaveModal />}
      {showLoadModal && <LoadModal />}
      {showConnectionsModal && <ConnectionsModal />}
      {showTrackingModal && <TrackingModal />}
      {showRunsModal && <RunsModal />}
      {profileTarget && <ProfileModal key={`${profileTarget.nodeId}:${profileTarget.port}`} />}
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <ReactFlowProvider>
        <AppInner />
      </ReactFlowProvider>
    </ErrorBoundary>
  )
}
