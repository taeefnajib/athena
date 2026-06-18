import { Component, type ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error('Athena UI crashed:', error, info)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div style={{
        position: 'fixed', inset: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg)', padding: 32,
      }}>
        <div style={{
          maxWidth: 560, background: 'var(--panel)', border: '1px solid var(--border)',
          borderRadius: 12, padding: 24, boxShadow: 'var(--shadow-lg)',
        }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--error)', marginBottom: 8 }}>
            Athena ran into a problem
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 16, lineHeight: 1.6 }}>
            The UI hit an unexpected error and stopped rendering. Try resetting below; if that doesn't work, reload the page.
            Your pipeline is autosaved — it will not be lost.
          </div>
          <pre style={{
            background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6,
            padding: 12, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--mono)',
            overflow: 'auto', maxHeight: 200, marginBottom: 16, whiteSpace: 'pre-wrap',
          }}>
            {this.state.error.message}
            {this.state.error.stack ? `\n\n${this.state.error.stack}` : ''}
          </pre>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)',
                background: 'var(--card)', color: 'var(--text)', cursor: 'pointer', fontSize: 12, fontWeight: 500,
              }}
            >
              Reload page
            </button>
            <button
              onClick={this.reset}
              style={{
                padding: '7px 16px', borderRadius: 6, border: 'none',
                background: 'var(--accent)', color: 'white', cursor: 'pointer', fontSize: 12, fontWeight: 600,
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }
}
