import type { ColumnProfile } from '../../lib/profile'
import { fmtNum } from '../../lib/profile'
import { HistogramChart, Tooltip, useTooltip } from './Charts'

const KIND_LABEL: Record<ColumnProfile['kind'], string> = {
  numeric: 'Number', binary: 'Binary', categorical: 'Category', text: 'Text', datetime: 'Date', empty: 'Empty',
}

const th: React.CSSProperties = { textAlign: 'left', padding: '6px 10px', fontSize: 10.5, fontWeight: 600, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--panel)', whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '7px 10px', fontSize: 11.5, color: 'var(--text-dim)', borderBottom: '1px solid var(--border)', verticalAlign: 'middle' }

function TopBars({ col, tooltip }: { col: ColumnProfile; tooltip: ReturnType<typeof useTooltip> }) {
  const top = (col.top ?? []).slice(0, 4)
  const total = (col.top ?? []).reduce((a, t) => a + t.count, 0) + (col.other_count ?? 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, width: 140 }}>
      {top.map(t => (
        <div key={t.value} tabIndex={0} style={{ display: 'flex', alignItems: 'center', gap: 6, outline: 'none' }}
             onPointerMove={e => tooltip.show(e, `${t.count.toLocaleString()} (${((100 * t.count) / Math.max(total, 1)).toFixed(1)}%)`, t.value)}
             onPointerLeave={tooltip.hide} onFocus={e => tooltip.show(e, t.count.toLocaleString(), t.value)} onBlur={tooltip.hide}>
          <div style={{ height: 6, width: `${Math.max(2, (t.count / Math.max(total, 1)) * 70)}px`, background: 'var(--chart-mark)', borderRadius: '0 3px 3px 0', flexShrink: 0 }} />
          <span style={{ fontSize: 10.5, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.value}</span>
        </div>
      ))}
      {(col.unique > top.length) && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>+{(col.unique - top.length).toLocaleString()} more</span>}
    </div>
  )
}

function Stats({ col }: { col: ColumnProfile }) {
  if (col.kind === 'numeric') {
    return <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>mean {fmtNum(col.mean)} · median {fmtNum(col.median)}<br />{fmtNum(col.min)} to {fmtNum(col.max)}</span>
  }
  if (col.kind === 'datetime') return <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{String(col.min ?? '–').slice(0, 10)} to {String(col.max ?? '–').slice(0, 10)}</span>
  if (col.top?.length) return <span>most common: <span style={{ color: 'var(--text)' }}>{col.top[0].value}</span></span>
  return <span>–</span>
}

export function ColumnsTable({ columns, flagged }: { columns: ColumnProfile[]; flagged: Set<string> }) {
  const tooltip = useTooltip()
  return (
    <div>
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr><th style={th}>Column</th><th style={th}>Type</th><th style={{ ...th, textAlign: 'right' }}>Missing</th><th style={{ ...th, textAlign: 'right' }}>Unique</th><th style={th}>Distribution</th><th style={th}>Summary</th></tr>
      </thead>
      <tbody>
        {columns.map(c => (
          <tr key={c.name}>
            <td style={{ ...td, color: 'var(--text)', fontWeight: 600, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.name}>
              {flagged.has(c.name) && <span title="Has a data-quality finding" style={{ color: 'var(--warning)', marginRight: 4 }}>⚠</span>}{c.name}
            </td>
            <td style={td}><span style={{ fontSize: 10.5, padding: '2px 6px', borderRadius: 99, background: 'var(--card2)', color: 'var(--text-dim)' }}>{KIND_LABEL[c.kind]}</span></td>
            <td style={{ ...td, textAlign: 'right', fontFamily: 'var(--mono)', color: c.missing_pct >= 20 ? 'var(--text)' : 'var(--text-dim)' }}>{c.missing ? `${c.missing_pct}%` : '–'}</td>
            <td style={{ ...td, textAlign: 'right', fontFamily: 'var(--mono)' }}>{c.unique.toLocaleString()}</td>
            <td style={td}>{c.histogram ? <HistogramChart hist={c.histogram} tooltip={tooltip} /> : c.top ? <TopBars col={c} tooltip={tooltip} /> : <span>–</span>}</td>
            <td style={td}><Stats col={c} /></td>
          </tr>
        ))}
      </tbody>
    </table>
    <Tooltip tip={tooltip.tip} />
    </div>
  )
}
