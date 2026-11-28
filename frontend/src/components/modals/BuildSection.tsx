import { useEffect, useState } from 'react'

export interface BuildStatus {
  target: 'docker' | 'bento' | 'push'; state: 'running' | 'succeeded' | 'failed' | 'cancelled'
  tag: string; started: number; finished: number | null; command: string; run_command: string; log: string[]
}
export interface BuildTool { available: boolean; command: string | null; hint: string | null }
export type BuildTools = Record<'docker' | 'bento', BuildTool>

const TARGETS = [
  { id: 'docker' as const, label: 'Build Docker image', what: 'Docker image' },
  { id: 'bento' as const, label: 'Build Bento', what: 'Bento' },
]

const btn: React.CSSProperties = { fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', cursor: 'pointer' }
const mono: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 11.5 }

/** The lines of a build's status, as plain data (tested). */
export function buildSummary(b: BuildStatus | null | undefined): { tone: 'running' | 'ok' | 'bad' | 'none'; text: string } {
  if (!b) return { tone: 'none', text: 'Not built yet.' }
  const took = b.finished ? ` in ${Math.max(1, Math.round(b.finished - b.started))} s` : ''
  if (b.target === 'push') {
    switch (b.state) {
      case 'running': return { tone: 'running', text: `Pushing ${b.tag}…` }
      case 'succeeded': return { tone: 'ok', text: `Pushed ${b.tag}${took}.` }
      case 'cancelled': return { tone: 'bad', text: 'The push was cancelled.' }
      default: return { tone: 'bad', text: `The push failed${took}: see the log (are you logged in to the registry?).` }
    }
  }
  const what = b.target === 'docker' ? 'Docker image' : 'Bento'
  switch (b.state) {
    case 'running': return { tone: 'running', text: `Building the ${what}…` }
    case 'succeeded': return { tone: 'ok', text: `Built ${what}${b.tag ? ` ${b.tag}` : ''}${took}.` }
    case 'cancelled': return { tone: 'bad', text: `The ${what} build was cancelled.` }
    default: return { tone: 'bad', text: `The ${what} build failed${took}: see the log.` }
  }
}

/** Build the bundle into a Docker image or a Bento with the user's own docker / bentoml, and show the log. */
export function BuildSection({ slug, build, tools, onStart, onCancel }: {
  slug: string; build: BuildStatus | null | undefined; tools: BuildTools | null
  onStart: (target: 'docker' | 'bento' | 'push', image?: string) => void; onCancel: () => void
}) {
  const running = build?.state === 'running'
  const [image, setImage] = useState(`${slug}:latest`)
  useEffect(() => { setImage(build && build.target !== 'bento' && build.tag ? build.tag : `${slug}:latest`) }, [slug])  // eslint-disable-line react-hooks/exhaustive-deps
  const built = build?.state === 'succeeded' && build.target !== 'bento' ? build.tag : ''
  const [showLog, setShowLog] = useState(false)
  useEffect(() => { if (running || build?.state === 'failed') setShowLog(true) }, [running, build?.state])
  const summary = buildSummary(build)
  const color = { running: 'var(--running)', ok: 'var(--success)', bad: 'var(--error)', none: 'var(--text-muted)' }[summary.tone]
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <label htmlFor={`image-${slug}`} style={{ fontSize: 11.5, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>Image name</label>
        <input id={`image-${slug}`} value={image} onChange={e => setImage(e.target.value)} spellCheck={false}
               style={{ ...mono, flex: 1, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px', color: 'var(--text)' }} />
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {TARGETS.map(t => {
          const tool = tools?.[t.id]
          return (
            <button key={t.id} style={{ ...btn, opacity: tool?.available && !running ? 1 : 0.55, cursor: tool?.available && !running ? 'pointer' : 'not-allowed' }} disabled={running || !tool?.available}
                    title={tool?.available ? `Runs ${tool.command} in the bundle folder` : tool?.hint ?? ''} onClick={() => onStart(t.id, t.id === 'docker' ? image.trim() : undefined)}>
              {t.label}
            </button>
          )
        })}
        <button style={{ ...btn, opacity: built && !running ? 1 : 0.55, cursor: built && !running ? 'pointer' : 'not-allowed' }} disabled={!built || running}
                title={built ? `docker push ${built} (log in to the registry first: docker login)` : 'Build the Docker image first'} onClick={() => onStart('push', built)}>
          Push image
        </button>
        {running && <button style={btn} onClick={onCancel}>Cancel build</button>}
        <span role="status" style={{ fontSize: 12, color }}>{summary.text}</span>
      </div>
      {tools && TARGETS.filter(t => !tools[t.id].available).map(t => (
        <div key={t.id} style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{t.what}: {tools[t.id].hint}</div>
      ))}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
        Building downloads the base image and the pinned packages, so it needs the internet the first time.
      </div>
      {build?.state === 'succeeded' && build.run_command && (
        <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-dim)' }}>
          Run it: <span style={{ ...mono, color: 'var(--text)', userSelect: 'all' }}>{build.run_command}</span>
          {build.target === 'bento' && <> · or make it an image: <span style={{ ...mono, userSelect: 'all' }}>bentoml containerize {build.tag}</span></>}
        </div>
      )}
      {build && build.log.length > 0 && (
        <details open={showLog} onToggle={e => setShowLog((e.target as HTMLDetailsElement).open)} style={{ marginTop: 6 }}>
          <summary style={{ fontSize: 11.5, color: 'var(--text-dim)', cursor: 'pointer' }}>Build log ({slug}/build.log)</summary>
          <pre aria-label="Build log" style={{ ...mono, fontSize: 11, margin: '6px 0 0', maxHeight: 220, overflow: 'auto', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-dim)', padding: 8, whiteSpace: 'pre-wrap' }}>
            {build.log.join('\n')}
          </pre>
        </details>
      )}
    </div>
  )
}
