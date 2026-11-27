import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles/globals.css'
import App from './App'
import { loadNodeRegistry } from './registry/nodeRegistry'

const root = ReactDOM.createRoot(document.getElementById('root')!)

function BackendUnavailable({ error }: { error: string }) {
  return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12, fontFamily: 'var(--font)', color: 'var(--text)', background: 'var(--bg)' }}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Couldn't reach the Athena backend</div>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', maxWidth: 420, textAlign: 'center', lineHeight: 1.6 }}>
        The node library is loaded from the backend at startup. Start it with <code style={{ fontFamily: 'var(--mono)' }}>npm run dev</code> and try again.
        <br /><span style={{ color: 'var(--text-muted)' }}>{error}</span>
      </div>
      <button onClick={() => void start()} style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border2)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer', fontSize: 12 }}>
        Retry
      </button>
    </div>
  )
}

async function start(): Promise<void> {
  try {
    await loadNodeRegistry()
    root.render(<React.StrictMode><App /></React.StrictMode>)
  } catch (e) {
    root.render(<BackendUnavailable error={e instanceof Error ? e.message : String(e)} />)
  }
}

void start()
