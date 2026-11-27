import { useUiStore } from '../../store/uiStore'
import { usePipelineStore, TEMPLATES } from '../../store/pipelineStore'

const TEMPLATE_META = [
  { id: 'classification' as const, label: 'Classification Starter', desc: 'CSV → Imputer → Scaler → Train/Test → Random Forest → Metrics + Confusion Matrix', nodes: 7 },
  { id: 'regression'    as const, label: 'Regression Pipeline',    desc: 'CSV → Imputer → Feature Gen → Train/Test → Linear Regression → Metrics + Residuals', nodes: 7 },
  { id: 'nlp'           as const, label: 'NLP Pipeline',           desc: 'CSV → TF-IDF Vectorizer → Train/Test → Logistic Regression → Metrics + SHAP', nodes: 6 },
  { id: 'automl'        as const, label: 'AutoML Classification',  desc: 'CSV → Imputer → Train/Test → AutoML Search (30 s, FLAML) → Metrics + Confusion Matrix', nodes: 6 },
  { id: 'forecasting'   as const, label: 'Sales Forecasting',      desc: 'Daily sales → Time Series Split → ETS vs seasonal-naive baseline, plus a 4-fold backtest (ETS needs the stats extra)', nodes: 5 },
  { id: 'clustering'    as const, label: 'Customer Segmentation',  desc: 'Customers → K-Means (picks k by silhouette) → Cluster Evaluation map and profile', nodes: 3 },
]

export function TemplatesModal() {
  const { setShowTemplatesModal, showToast } = useUiStore()
  const { loadPipeline } = usePipelineStore()

  const onLoad = (id: keyof typeof TEMPLATES) => {
    const t = TEMPLATES[id]
    loadPipeline(t.nodes, t.edges)
    setShowTemplatesModal(false)
    showToast(`Loaded ${id} template`, 'success')
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowTemplatesModal(false)}>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 440, maxWidth: 'calc(100vw - 32px)', maxHeight: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: '18px 20px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Pipeline Templates</div>
          <button onClick={() => setShowTemplatesModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>×</button>
        </div>
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
          {TEMPLATE_META.map(t => (
            <div
              key={t.id}
              onClick={() => onLoad(t.id)}
              style={{ padding: '12px 14px', borderRadius: 8, border: '1px solid var(--border)', cursor: 'pointer', transition: 'all 0.15s' }}
              onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'var(--card)'; el.style.borderColor = 'var(--accent)' }}
              onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'transparent'; el.style.borderColor = 'var(--border)' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{t.label}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', background: 'var(--card2)', padding: '2px 7px', borderRadius: 99 }}>{t.nodes} nodes</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{t.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
