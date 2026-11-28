import { AnimatePresence, motion } from 'framer-motion'
import { useUiStore } from '../../store/uiStore'

const COLORS: Record<string, string> = {
  info: 'var(--accent)',
  success: 'var(--success)',
  error: 'var(--error)',
  warn: 'var(--warning)',
}

export function Toaster() {
  const toast = useUiStore(s => s.toast)
  const clearToast = useUiStore(s => s.clearToast)

  return (
    <AnimatePresence>
      {toast && (
        <motion.div
          key={toast.msg}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.2 }}
          onClick={clearToast}
          style={{
            position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
            background: 'var(--card)', border: `1px solid ${COLORS[toast.type] ?? 'var(--border)'}`,
            borderRadius: 8, padding: '9px 18px', display: 'flex', alignItems: 'center', gap: 8,
            boxShadow: 'var(--shadow-lg)', zIndex: 9999, fontSize: 13, cursor: 'pointer',
            maxWidth: 'min(720px, calc(100vw - 32px))', overflowWrap: 'anywhere',  // long paths wrap instead of running off-screen
          }}
        >
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: COLORS[toast.type], flexShrink: 0 }} />
          <span style={{ color: 'var(--text)' }}>{toast.msg}</span>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
