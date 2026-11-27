// Small single-series charts for the data profile. One mark colour (--chart-mark, validated per theme),
// text in text tokens, 2px gaps between bars, 4px rounded data-ends, and a hover/focus tooltip on every mark.
import { useCallback, useState } from 'react'
import type { Histogram } from '../../lib/profile'
import { fmtNum } from '../../lib/profile'

export interface Tip { x: number; y: number; value: string; label: string }

/** One tooltip per chart container; marks call show() on pointer move / focus and hide() on leave / blur. */
export function useTooltip() {
  const [tip, setTip] = useState<Tip | null>(null)
  const show = useCallback((e: React.PointerEvent | React.FocusEvent, value: string, label: string) => {
    const r = (e.currentTarget as Element).getBoundingClientRect()
    const x = 'clientX' in e ? e.clientX : r.left + r.width / 2
    setTip({ x, y: r.top, value, label })
  }, [])
  const hide = useCallback(() => setTip(null), [])
  return { tip, show, hide }
}

export function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null
  return (
    <div role="tooltip" style={{
      position: 'fixed', left: tip.x, top: tip.y - 8, transform: 'translate(-50%, -100%)', zIndex: 2000, pointerEvents: 'none',
      background: 'var(--card2)', border: '1px solid var(--border2)', borderRadius: 6, padding: '5px 8px', boxShadow: 'var(--shadow)',
      display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
    }}>
      <span style={{ width: 10, height: 2, background: 'var(--chart-mark)', borderRadius: 1 }} />
      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--mono)' }}>{tip.value}</span>
      <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{tip.label}</span>
    </div>
  )
}

/** Column histogram (sparkline size by default). Bars grow from one baseline; hover shows the bin and its count. */
export function HistogramChart({ hist, width = 140, height = 32, tooltip }: {
  hist: Histogram; width?: number; height?: number; tooltip: ReturnType<typeof useTooltip>
}) {
  const n = hist.counts.length
  const max = Math.max(1, ...hist.counts)
  const gap = 2
  const bw = Math.min(24, Math.max(1, (width - gap * (n - 1)) / n))
  const [hover, setHover] = useState<number | null>(null)
  return (
    <svg width={width} height={height} role="img" aria-label="Distribution" style={{ display: 'block', overflow: 'visible' }}>
      <line x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} stroke="var(--chart-grid)" strokeWidth={1} />
      {hist.counts.map((c, i) => {
        const h = c === 0 ? 0 : Math.max(2, (c / max) * (height - 1))
        const x = i * (bw + gap)
        const label = `${fmtNum(hist.edges[i])} – ${fmtNum(hist.edges[i + 1])}`
        return (
          <g key={i} tabIndex={0} style={{ outline: 'none', cursor: 'default' }}
             onPointerMove={e => { setHover(i); tooltip.show(e, c.toLocaleString(), label) }}
             onPointerLeave={() => { setHover(null); tooltip.hide() }}
             onFocus={e => { setHover(i); tooltip.show(e, c.toLocaleString(), label) }}
             onBlur={() => { setHover(null); tooltip.hide() }}>
            <rect x={x - gap / 2} y={0} width={bw + gap} height={height} fill="transparent" />
            {h > 0 && <path d={roundedTop(x, height - 1, bw, h)} fill={hover === i ? 'var(--chart-mark-hover)' : 'var(--chart-mark)'} />}
          </g>
        )
      })}
    </svg>
  )
}

/** A column (x, baseline y) of width w and height h, with 4px rounded top corners and a square base. */
function roundedTop(x: number, base: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h)
  const top = base - h
  return `M${x},${base} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${base} Z`
}

/** Ranked horizontal bars with the label on the left and the value at the bar tip. */
export function BarList({ rows, valueLabel, format = v => v.toLocaleString(), tooltip, max: maxOverride }: {
  rows: Array<{ label: string; value: number; note?: string }>
  valueLabel: string
  format?: (v: number) => string
  tooltip: ReturnType<typeof useTooltip>
  max?: number
}) {
  const max = maxOverride ?? Math.max(1e-12, ...rows.map(r => r.value))
  const [hover, setHover] = useState<number | null>(null)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {rows.map((r, i) => (
        <div key={r.label + i} tabIndex={0} style={{ display: 'grid', gridTemplateColumns: 'minmax(80px, 34%) 1fr', alignItems: 'center', gap: 8, padding: '2px 0', outline: 'none' }}
             onPointerMove={e => { setHover(i); tooltip.show(e, format(r.value), `${r.label} · ${valueLabel}${r.note ? ` · ${r.note}` : ''}`) }}
             onPointerLeave={() => { setHover(null); tooltip.hide() }}
             onFocus={e => { setHover(i); tooltip.show(e, format(r.value), `${r.label} · ${valueLabel}`) }}
             onBlur={() => { setHover(null); tooltip.hide() }}>
          <span title={r.label} style={{ fontSize: 11.5, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'right' }}>{r.label}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <div style={{
              height: 14, width: `${Math.max(0.5, (r.value / max) * 85)}%`, borderRadius: '0 4px 4px 0',
              background: hover === i ? 'var(--chart-mark-hover)' : 'var(--chart-mark)', flexShrink: 0,
            }} />
            <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'var(--mono)', whiteSpace: 'nowrap' }}>{format(r.value)}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
