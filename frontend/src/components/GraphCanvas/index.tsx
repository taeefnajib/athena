import { useCallback, useEffect, useMemo, useRef } from 'react'
import {
  ReactFlow, Background, Controls, ControlButton, MiniMap,
  type Connection, type Edge, type Node,
  type NodeChange, type EdgeChange,
  useNodesState, useEdgesState, useReactFlow,
  BackgroundVariant,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { nodeTypes } from '../../nodes'
import { usePipelineStore, type PipelineNode, type PipelineEdge } from '../../store/pipelineStore'
import { useExecutionStore } from '../../store/executionStore'
import { useUiStore } from '../../store/uiStore'
import { NODE_REGISTRY, CATEGORY_META } from '../../registry/nodeRegistry'
import { isValidConnection } from '../../lib/validation'
import { autoLayout } from '../../lib/layout'
import { Network } from 'lucide-react'

function toRfNode(n: PipelineNode): Node {
  return {
    id: n.id,
    type: 'athena_node',
    position: n.position,
    data: { nodeType: n.type, config: n.config },
  }
}

function toRfEdge(e: PipelineEdge): Edge {
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: `output-${e.sourcePort}`,
    targetHandle: `input-${e.targetPort}`,
    style: { stroke: 'var(--text-muted)', strokeWidth: 1.5 },
  }
}

export function GraphCanvas() {
  const storeNodes = usePipelineStore(s => s.nodes)
  const storeEdges = usePipelineStore(s => s.edges)
  const moveNode = usePipelineStore(s => s.moveNode)
  const removeNode = usePipelineStore(s => s.removeNode)
  const removeEdge = usePipelineStore(s => s.removeEdge)
  const addEdge = usePipelineStore(s => s.addEdge)
  const addNode = usePipelineStore(s => s.addNode)
  const setSelectedNode = usePipelineStore(s => s.setSelectedNode)
  const setSelectedEdge = usePipelineStore(s => s.setSelectedEdge)
  const selectedEdgeId = usePipelineStore(s => s.selectedEdgeId)

  const fitViewGeneration = usePipelineStore(s => s.fitViewGeneration)
  const execStatus = useExecutionStore(s => s.status)
  const showToast = useUiStore(s => s.showToast)
  const { screenToFlowPosition, fitView } = useReactFlow()
  const applyLayout = usePipelineStore(s => s.applyLayout)
  const tidyToast = useUiStore(s => s.showToast)
  // Tidy layout: an explicit, undoable command (auto-layout never moves nodes on its own).
  const tidy = useCallback(() => {
    const { nodes, edges } = usePipelineStore.getState()
    if (nodes.length === 0) return
    const ports = (type: string) => Math.max(NODE_REGISTRY[type]?.inputs.length ?? 1, NODE_REGISTRY[type]?.outputs.length ?? 1)
    applyLayout(autoLayout(nodes.map(n => ({ id: n.id, ports: ports(n.type) })), edges))
    tidyToast('Arranged the nodes. Ctrl+Z to undo', 'info')
  }, [applyLayout, tidyToast])

  const [rfNodes, setRfNodes, onNodesChangeBase] = useNodesState<Node>(storeNodes.map(toRfNode))
  const [rfEdges, setRfEdges, onEdgesChangeBase] = useEdgesState<Edge>(storeEdges.map(toRfEdge))

  const lastSyncedNodes = useRef<PipelineNode[]>(storeNodes)
  const lastSyncedEdges = useRef<PipelineEdge[]>(storeEdges)

  useEffect(() => {
    if (storeNodes === lastSyncedNodes.current) return
    const prev = lastSyncedNodes.current
    lastSyncedNodes.current = storeNodes

    const prevMap = new Map(prev.map(n => [n.id, n]))
    const currIds = new Set(storeNodes.map(n => n.id))
    const added = storeNodes.filter(n => !prevMap.has(n.id))
    const anyRemoved = prev.some(n => !currIds.has(n.id))
    const anyChanged = storeNodes.some(n => {
      const p = prevMap.get(n.id)
      return p && (p.type !== n.type || p.config !== n.config)
    })

    if (!anyRemoved && !anyChanged && added.length > 0) {
      // Pure addition: append only the new nodes so React Flow doesn't treat
      // the whole set as re-initialized (which would re-trigger fitView and
      // shift the viewport, causing subsequent drops to land at wrong positions).
      setRfNodes(existing => [...existing, ...added.map(toRfNode)])
      return
    }

    if (anyRemoved || anyChanged || added.length > 0) {
      setRfNodes(storeNodes.map(toRfNode))
      return
    }

    // Positions changed in the store (Tidy layout, undo/redo): move just those nodes. After an ordinary drag the
    // canvas already shows the stored position, so nothing changes.
    const target = new Map(storeNodes.map(n => [n.id, n.position]))
    setRfNodes(existing => {
      let moved = false
      const next = existing.map(n => {
        const p = target.get(n.id)
        if (p && (p.x !== n.position.x || p.y !== n.position.y)) { moved = true; return { ...n, position: p } }
        return n
      })
      return moved ? next : existing
    })
  }, [storeNodes, setRfNodes])

  useEffect(() => {
    if (storeEdges === lastSyncedEdges.current) return
    const prev = lastSyncedEdges.current
    lastSyncedEdges.current = storeEdges

    const idsChanged =
      storeEdges.length !== prev.length ||
      storeEdges.some((e, i) => e.id !== prev[i]?.id)
    if (idsChanged) {
      setRfEdges(storeEdges.map(toRfEdge))
    }
  }, [storeEdges, setRfEdges])

  // Fit the viewport to all nodes after a pipeline load (not after individual drops).
  // Using a small delay so nodes have time to render with measured dimensions before
  // fitView calculates bounds.
  useEffect(() => {
    if (fitViewGeneration === 0) return
    const timer = setTimeout(() => fitView({ padding: 0.2 }), 100)
    return () => clearTimeout(timer)
  }, [fitViewGeneration, fitView])

  // Handle React Flow's internal change events
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    onNodesChangeBase(changes)
    for (const c of changes) {
      // Persist position only on drag end (not during the drag)
      if (c.type === 'position' && c.position && c.dragging === false) {
        moveNode(c.id, c.position)
      } else if (c.type === 'remove') {
        removeNode(c.id)
      }
    }
  }, [onNodesChangeBase, moveNode, removeNode])

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    onEdgesChangeBase(changes)
    for (const c of changes) {
      if (c.type === 'remove') removeEdge(c.id)
    }
  }, [onEdgesChangeBase, removeEdge])

  const onConnect = useCallback((conn: Connection) => {
    if (!conn.source || !conn.target) return
    const srcNode = storeNodes.find(n => n.id === conn.source)
    const tgtNode = storeNodes.find(n => n.id === conn.target)
    if (!srcNode || !tgtNode) return

    const srcPortIdx = conn.sourceHandle ? parseInt(conn.sourceHandle.replace('output-', ''), 10) : 0
    const tgtPortIdx = conn.targetHandle ? parseInt(conn.targetHandle.replace('input-', ''), 10) : 0

    if (!isValidConnection(srcNode.type, srcPortIdx, tgtNode.type, tgtPortIdx)) {
      const srcPort = NODE_REGISTRY[srcNode.type]?.outputs[srcPortIdx]
      const tgtPort = NODE_REGISTRY[tgtNode.type]?.inputs[tgtPortIdx]
      showToast(`Incompatible ports: "${srcPort?.type}" → "${tgtPort?.type}"`, 'error')
      return
    }

    addEdge({
      id: `e_${Date.now()}`,
      source: conn.source,
      target: conn.target,
      sourcePort: srcPortIdx,
      targetPort: tgtPortIdx,
    })
  }, [storeNodes, addEdge, showToast])

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/athena-node')
    if (!type) return
    // screenToFlowPosition converts absolute client coords → flow coords,
    // accounting for the current zoom level and pan offset.
    // snapToGrid: false so we do the snap ourselves below.
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY }, { snapToGrid: false })
    addNode(type, {
      x: Math.round(pos.x / 20) * 20,
      y: Math.round(pos.y / 20) * 20,
    })
  }, [addNode, screenToFlowPosition])

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node.id)
  }, [setSelectedNode])

  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelectedEdge(edge.id)
  }, [setSelectedEdge])

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
    setSelectedEdge(null)
  }, [setSelectedNode, setSelectedEdge])

  const nodeColor = useCallback((node: Node) => {
    const spec = NODE_REGISTRY[node.data?.nodeType as string]
    if (!spec) return '#888'
    return CATEGORY_META[spec.category]?.color ?? '#888'
  }, [])

  const displayedEdges = useMemo(
    () => rfEdges.map(e => ({
      ...e,
      animated: execStatus === 'running',
      style: {
        stroke: e.id === selectedEdgeId ? 'var(--accent)' : 'var(--text-muted)',
        strokeWidth: e.id === selectedEdgeId ? 2.5 : 1.5,
      },
    })),
    [rfEdges, execStatus, selectedEdgeId],
  )

  return (
    <div style={{ flex: 1, height: '100%', minWidth: 0 }} className="canvas-grid-dark">
      <ReactFlow
        nodes={rfNodes}
        edges={displayedEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={onPaneClick}
        onDrop={onDrop}
        onDragOver={e => e.preventDefault()}
        deleteKeyCode={null}
        connectOnClick={false}
        snapToGrid
        snapGrid={[20, 20]}
        defaultEdgeOptions={{ animated: false, style: { stroke: 'var(--text-muted)', strokeWidth: 1.5 } }}
        style={{ background: 'transparent' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.5} color="var(--border)" />
        <Controls>
          <ControlButton onClick={tidy} title="Tidy layout: arrange nodes left to right (Ctrl+Z undoes it)" aria-label="Tidy layout">
            <Network size={14} />
          </ControlButton>
        </Controls>
        <MiniMap
          nodeColor={nodeColor}
          style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 8 }}
        />
      </ReactFlow>
    </div>
  )
}
