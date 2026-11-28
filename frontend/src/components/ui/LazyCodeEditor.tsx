import { lazy, Suspense, type ComponentProps } from 'react'
import type { CodeEditor as Editor } from './CodeEditor'

// CodeMirror and its languages are ~180 kB gzipped: load them the first time a code view appears, not at start-up.
const CodeEditorImpl = lazy(() => import('./CodeEditor').then(m => ({ default: m.CodeEditor })))

export function CodeEditor(props: ComponentProps<typeof Editor>) {
  return (
    <Suspense fallback={
      <pre style={{ margin: 0, minHeight: props.minHeight ?? 120, padding: '6px 10px', background: 'var(--card)', border: '1px solid var(--border)',
                    borderRadius: 6, color: 'var(--text-dim)', fontFamily: 'var(--mono)', fontSize: 11.5, whiteSpace: 'pre-wrap', overflow: 'hidden' }}>
        {props.value}
      </pre>
    }>
      <CodeEditorImpl {...props} />
    </Suspense>
  )
}
