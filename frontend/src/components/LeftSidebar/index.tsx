import { useState, useMemo } from 'react'
import { getNodeGroups, type NodeSpec } from '../../registry/nodeRegistry'
import { SubflowLibrary } from './SubflowLibrary'

export function LeftSidebar() {
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    const groups = getNodeGroups()
    if (!q) return groups
    return groups
      .map(g => ({ ...g, nodes: g.nodes.filter(n => n.label.toLowerCase().includes(q) || n.description.toLowerCase().includes(q)) }))
      .filter(g => g.nodes.length > 0)
  }, [search])

  const toggle = (id: string) => setCollapsed(p => ({ ...p, [id]: !p[id] }))

  return (
    <div style={{ width: 240, minWidth: 240, background: 'var(--panel)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '14px 14px 10px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 8 }}>
          Node Library
        </div>
        <input
          style={{ width: '100%', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'var(--text)', fontSize: 12, outline: 'none', fontFamily: 'var(--font)' }}
          placeholder="Search nodes…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        <SubflowLibrary search={search} />
        {filtered.map(group => (
          <div key={group.id}>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', cursor: 'pointer', userSelect: 'none', fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', color: 'var(--text-dim)' }}
              onClick={() => toggle(group.id)}
            >
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: group.color, flexShrink: 0 }} />
              <span style={{ color: group.color }}>{group.icon}</span>
              <span>{group.label}</span>
              <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--text-muted)', transition: 'transform 0.15s', transform: collapsed[group.id] ? 'rotate(-90deg)' : 'rotate(0deg)', display: 'inline-block' }}>▾</span>
            </div>
            {!collapsed[group.id] && group.nodes.map(node => (
              <NodeLibItem key={node.type} node={node} color={group.color} />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function NodeLibItem({ node, color }: { node: NodeSpec; color: string }) {
  const [hov, setHov] = useState(false)

  const onDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('application/athena-node', node.type)
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 14px 5px 26px', cursor: 'grab', background: hov ? 'var(--card)' : 'transparent', transition: 'background 0.1s', userSelect: 'none' }}
      draggable
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      onDragStart={onDragStart}
      title={node.description}
    >
      <div style={{ width: 5, height: 5, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span style={{ fontSize: 12, color: hov ? 'var(--text)' : 'var(--text-dim)', transition: 'color 0.1s', lineHeight: 1.3 }}>{node.label}</span>
    </div>
  )
}
