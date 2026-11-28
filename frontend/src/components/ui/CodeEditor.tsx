import { useEffect, useRef } from 'react'
import { basicSetup } from 'codemirror'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'
import { python } from '@codemirror/lang-python'
import { sql } from '@codemirror/lang-sql'

export type CodeLanguage = 'python' | 'sql'

// Colours come from theme variables (index.html), so the editor follows light / dark mode.
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.operatorKeyword, t.definitionKeyword, t.moduleKeyword], color: 'var(--code-keyword)' },
  { tag: [t.string, t.special(t.string)], color: 'var(--code-string)' },
  { tag: [t.number, t.bool, t.null], color: 'var(--code-number)' },
  { tag: [t.comment, t.lineComment, t.blockComment], color: 'var(--code-comment)', fontStyle: 'italic' },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: 'var(--code-function)' },
  { tag: [t.className, t.typeName], color: 'var(--code-function)' },
])

const theme = EditorView.theme({
  '&': { backgroundColor: 'var(--card)', color: 'var(--text)', fontSize: '11.5px', border: '1px solid var(--border)', borderRadius: '6px' },
  '&.cm-focused': { outline: 'none', borderColor: 'var(--accent)' },
  '.cm-scroller': { fontFamily: 'var(--mono)', lineHeight: '1.55', fontVariantLigatures: 'none' },  // show != as typed, not ≠
  '.cm-content': { caretColor: 'var(--text)' },
  '.cm-gutters': { backgroundColor: 'var(--card)', color: 'var(--text-muted)', border: 'none', borderRight: '1px solid var(--border)' },
  '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'transparent' },
  '&.cm-focused .cm-activeLine': { backgroundColor: 'var(--card2)' },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection': { backgroundColor: 'var(--code-selection) !important' },
  '.cm-cursor': { borderLeftColor: 'var(--text)' },
  '.cm-tooltip': { backgroundColor: 'var(--card2)', border: '1px solid var(--border2)', color: 'var(--text)' },
  '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'var(--accent)', color: 'white' },
  '.cm-foldPlaceholder': { backgroundColor: 'var(--card2)', border: 'none', color: 'var(--text-muted)' },
})

/** CodeMirror 6 editor. Editable editors commit on blur (like the inspector's text fields, so typing doesn't
 *  flood undo history); a ``value`` changed from outside (undo, another node) replaces the content. */
export function CodeEditor({ value, language, readOnly = false, onChange, minHeight = 120, maxHeight = 420, ariaLabel, wrap = true }: {
  value: string
  language: CodeLanguage
  readOnly?: boolean
  onChange?: (value: string) => void
  minHeight?: number
  maxHeight?: number
  ariaLabel?: string
  /** Wrap long lines (editable fields); off scrolls horizontally, which keeps identifiers whole (generated code). */
  wrap?: boolean
}) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const lastCommitted = useRef(value)  // what the store holds: blur commits only real edits

  useEffect(() => {
    if (!host.current) return
    const commit = (v: EditorView) => {
      const text = v.state.doc.toString()
      if (onChangeRef.current && text !== lastCommitted.current) { lastCommitted.current = text; onChangeRef.current(text) }
    }
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup, theme, syntaxHighlighting(highlight), language === 'sql' ? sql() : python(),
          EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly), ...(wrap ? [EditorView.lineWrapping] : []),
          EditorView.theme({ '.cm-scroller': { minHeight: `${minHeight}px`, maxHeight: `${maxHeight}px` } }),
          EditorView.domEventHandlers({ blur: (_e, ev) => { commit(ev); return false } }),
          EditorView.contentAttributes.of({ 'aria-label': ariaLabel ?? `${language} code` }),
        ],
      }),
    })
    view.current = v
    return () => { commit(v); v.destroy(); view.current = null }
    // The editor is created once per language/readOnly; content updates go through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, readOnly, wrap])

  useEffect(() => {
    const v = view.current
    lastCommitted.current = value
    if (v && v.state.doc.toString() !== value && !v.hasFocus) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } })
    }
  }, [value])

  return <div ref={host} />
}
