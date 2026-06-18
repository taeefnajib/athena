import { useUiStore } from '../../store/uiStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { api } from '../../lib/api'

const FORMATS = [
  { id: 'python',   label: 'Python Script',       icon: '🐍', desc: 'Clean pandas + scikit-learn code' },
  { id: 'notebook', label: 'Jupyter Notebook',     icon: '📓', desc: 'Interactive .ipynb with cells' },
  { id: 'json',     label: 'Pipeline JSON',        icon: '⚙',  desc: 'Serialized pipeline configuration' },
  { id: 'model',    label: 'Trained Model (.pkl)', icon: '💾', desc: 'Download serialized model file' },
]

export function ExportModal() {
  const { setShowExportModal, showToast } = useUiStore()
  const toPipelineSpec = usePipelineStore(s => s.toPipelineSpec)

  const onExport = async (format: string) => {
    try {
      const blob = await api.exportPipeline(toPipelineSpec(), format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = format === 'python' ? 'pipeline.py' : format === 'notebook' ? 'pipeline.ipynb' : format === 'json' ? 'pipeline.json' : 'model.pkl'
      a.click()
      URL.revokeObjectURL(url)
      setShowExportModal(false)
      showToast(`Exported as ${format}`, 'success')
    } catch {
      showToast('Export failed — run the pipeline first', 'error')
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowExportModal(false)}>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 420, boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '18px 20px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Export Pipeline</div>
          <button onClick={() => setShowExportModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>×</button>
        </div>
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {FORMATS.map(f => (
            <div
              key={f.id}
              onClick={() => onExport(f.id)}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', cursor: 'pointer', transition: 'all 0.15s' }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--card)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
            >
              <span style={{ fontSize: 20 }}>{f.icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{f.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{f.desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 14 }}>↓</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
