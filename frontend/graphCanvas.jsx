// Graph Canvas — pan, zoom, drag nodes, magnetic connections, edge selection

const { useState: useStateC, useRef: useRefC, useEffect: useEffectC, useCallback: useCallbackC } = React;

const NODE_WIDTH = 200;
const PORT_R = 6;
const SNAP_RADIUS = 52; // px in world-space for magnetic snap

function getPortPos(node, portType, portIdx) {
  const y = node.y + 36 + (portIdx + 0.5) * 26;
  const x = portType === 'output' ? node.x + NODE_WIDTH : node.x;
  return { x, y };
}

function getBezier(x1, y1, x2, y2) {
  const dx = Math.abs(x2 - x1) * 0.5;
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

function GraphCanvas({
  nodes, edges, selectedId, status, runningNodeId,
  onNodesChange, onEdgesChange, onSelectNode, onDropNode,
  selectedEdgeId, onSelectEdge
}) {
  const canvasRef = useRefC(null);
  const [pan, setPan] = useStateC({ x: 120, y: 60 });
  const [zoom, setZoom] = useStateC(1);
  const [dragging, setDragging] = useStateC(null);      // { id, ox, oy }
  const [panning, setPanning] = useStateC(null);         // { sx, sy, px, py }
  const [connecting, setConnecting] = useStateC(null);   // { sourceId, sourcePortIdx }
  const [mousePos, setMousePos] = useStateC({ x: 0, y: 0 });
  const [snapTarget, setSnapTarget] = useStateC(null);   // { nodeId, portIdx, x, y }
  const stateRef = useRefC({});
  stateRef.current = { pan, zoom, nodes, edges, dragging, panning, connecting, selectedId, selectedEdgeId };

  const toCanvas = useCallbackC((cx, cy) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (cx - rect.left - stateRef.current.pan.x) / stateRef.current.zoom,
      y: (cy - rect.top - stateRef.current.pan.y) / stateRef.current.zoom,
    };
  }, []);

  // ── Wheel zoom ─────────────────────────────────────────────────────────────
  const onWheel = useCallbackC((e) => {
    e.preventDefault();
    const rect = canvasRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY > 0 ? 0.92 : 1.08;
    setZoom(z => {
      const nz = Math.min(2.5, Math.max(0.2, z * factor));
      setPan(p => ({
        x: mx - (mx - p.x) * (nz / z),
        y: my - (my - p.y) * (nz / z),
      }));
      return nz;
    });
  }, []);

  useEffectC(() => {
    const el = canvasRef.current;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  // ── Magnetic snap helper ────────────────────────────────────────────────────
  const findSnap = useCallbackC((worldX, worldY, sourceId) => {
    let best = null, bestDist = SNAP_RADIUS;
    for (const node of stateRef.current.nodes) {
      if (node.id === sourceId) continue;
      const def = NODE_REGISTRY[node.type];
      if (!def) continue;
      def.inputs.forEach((_, idx) => {
        const pos = getPortPos(node, 'input', idx);
        const d = Math.hypot(pos.x - worldX, pos.y - worldY);
        if (d < bestDist) { best = { nodeId: node.id, portIdx: idx, ...pos }; bestDist = d; }
      });
    }
    return best;
  }, []);

  // ── Mouse events ────────────────────────────────────────────────────────────
  const onMouseDownCanvas = (e) => {
    // Deselect if the click is not on or inside a node element
    if (!e.target.closest('[data-nodeid]')) {
      onSelectNode(null);
      onSelectEdge(null);
      setPanning({ sx: e.clientX, sy: e.clientY, px: pan.x, py: pan.y });
    }
  };

  const onMouseMove = (e) => {
    const { dragging, panning, connecting } = stateRef.current;
    if (panning) {
      setPan({ x: panning.px + e.clientX - panning.sx, y: panning.py + e.clientY - panning.sy });
    }
    if (dragging) {
      const pos = toCanvas(e.clientX, e.clientY);
      onNodesChange(prev => prev.map(n => n.id === dragging.id
        ? { ...n, x: Math.round((pos.x - dragging.ox) / 20) * 20, y: Math.round((pos.y - dragging.oy) / 20) * 20 }
        : n));
    }
    if (connecting) {
      const pos = toCanvas(e.clientX, e.clientY);
      setMousePos(pos);
      // Magnetic snap
      const snap = findSnap(pos.x, pos.y, connecting.sourceId);
      setSnapTarget(snap || null);
    }
  };

  const onMouseUp = (e) => {
    const { connecting } = stateRef.current;
    setPanning(null);
    setDragging(null);

    if (connecting) {
      // Use snap target if available, else check port under cursor
      const snap = snapTarget;
      if (snap) {
        const exists = stateRef.current.edges.some(
          ed => ed.sourceId === connecting.sourceId && ed.sourcePortIdx === connecting.sourcePortIdx
            && ed.targetId === snap.nodeId && ed.targetPortIdx === snap.portIdx
        );
        if (!exists) {
          onEdgesChange(prev => [...prev, {
            id: `e_${Date.now()}`,
            sourceId: connecting.sourceId, sourcePortIdx: connecting.sourcePortIdx,
            targetId: snap.nodeId, targetPortIdx: snap.portIdx,
          }]);
        }
      }
      setConnecting(null);
      setSnapTarget(null);
    }
  };

  const startDrag = (e, nodeId) => {
    e.stopPropagation();
    const node = stateRef.current.nodes.find(n => n.id === nodeId);
    const pos = toCanvas(e.clientX, e.clientY);
    setDragging({ id: nodeId, ox: pos.x - node.x, oy: pos.y - node.y });
  };

  const startConnect = (e, nodeId, portIdx) => {
    e.stopPropagation(); e.preventDefault();
    const node = stateRef.current.nodes.find(n => n.id === nodeId);
    const pos = getPortPos(node, 'output', portIdx);
    setConnecting({ sourceId: nodeId, sourcePortIdx: portIdx });
    setMousePos(pos);
    setSnapTarget(null);
  };

  // Click on input port removes existing connection to it
  const clickInputPort = (e, nodeId, portIdx) => {
    e.stopPropagation();
    const { connecting } = stateRef.current;
    if (connecting) {
      // Complete connection
      endConnect(e, nodeId, portIdx);
      return;
    }
    // Remove existing edge going into this port
    onEdgesChange(prev => prev.filter(ed => !(ed.targetId === nodeId && ed.targetPortIdx === portIdx)));
  };

  const endConnect = (e, nodeId, portIdx) => {
    e.stopPropagation();
    const { connecting } = stateRef.current;
    if (!connecting || connecting.sourceId === nodeId) return;
    const exists = stateRef.current.edges.some(
      ed => ed.sourceId === connecting.sourceId && ed.sourcePortIdx === connecting.sourcePortIdx
        && ed.targetId === nodeId && ed.targetPortIdx === portIdx
    );
    if (!exists) {
      onEdgesChange(prev => [...prev, {
        id: `e_${Date.now()}`,
        sourceId: connecting.sourceId, sourcePortIdx: connecting.sourcePortIdx,
        targetId: nodeId, targetPortIdx: portIdx,
      }]);
    }
    setConnecting(null);
    setSnapTarget(null);
  };

  // ── Keyboard: Delete selected edge or node ──────────────────────────────────
  useEffectC(() => {
    const handler = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (stateRef.current.selectedEdgeId) {
          onEdgesChange(prev => prev.filter(ed => ed.id !== stateRef.current.selectedEdgeId));
          onSelectEdge(null);
        } else if (stateRef.current.selectedId) {
          const id = stateRef.current.selectedId;
          onNodesChange(prev => prev.filter(n => n.id !== id));
          onEdgesChange(prev => prev.filter(ed => ed.sourceId !== id && ed.targetId !== id));
          onSelectNode(null);
        }
      }
      if (e.key === 'Escape') { onSelectNode(null); onSelectEdge(null); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onEdgesChange, onNodesChange, onSelectNode, onSelectEdge]);

  const onDrop = (e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('nodeType');
    if (!type) return;
    const pos = toCanvas(e.clientX, e.clientY);
    onDropNode(type, Math.round(pos.x / 20) * 20, Math.round(pos.y / 20) * 20);
  };

  const isRunning = status === 'running';

  const containerStyle = {
    flex: 1, position: 'relative', overflow: 'hidden',
    cursor: panning ? 'grabbing' : connecting ? 'crosshair' : 'default',
    background: 'var(--bg)',
    transition: 'width 0.3s ease',
  };
  const transformStyle = {
    position: 'absolute', top: 0, left: 0,
    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
    transformOrigin: '0 0',
    width: 5000, height: 4000,
  };

  return (
    <div
      ref={canvasRef}
      style={containerStyle}
      className="canvas-grid-dark"
      onMouseDown={onMouseDownCanvas}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      onDrop={onDrop}
      onDragOver={e => e.preventDefault()}
    >
      <div style={transformStyle}>
        {/* SVG edge layer */}
        <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', overflow: 'visible', pointerEvents: 'none' }}>
          <defs>
            <marker id="arrow-dim" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="var(--text-muted)" opacity="0.6" />
            </marker>
            <marker id="arrow-sel" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="var(--accent)" />
            </marker>
            <marker id="arrow-run" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="var(--accent)" />
            </marker>
          </defs>

          {edges.map(edge => {
            const src = nodes.find(n => n.id === edge.sourceId);
            const tgt = nodes.find(n => n.id === edge.targetId);
            if (!src || !tgt) return null;
            const p1 = getPortPos(src, 'output', edge.sourcePortIdx);
            const p2 = getPortPos(tgt, 'input', edge.targetPortIdx);
            const d = getBezier(p1.x, p1.y, p2.x, p2.y);
            const isEdgeSel = selectedEdgeId === edge.id;
            const nodeInvolved = selectedId === edge.sourceId || selectedId === edge.targetId;
            const catColor = CATEGORY_META[NODE_REGISTRY[src.type]?.cat]?.color || 'var(--accent)';

            // Running: animate flow; selected: accent; default: muted
            const stroke = isEdgeSel ? 'var(--accent)' : (isRunning ? catColor : 'var(--text-muted)');
            const strokeW = isEdgeSel ? 2.5 : isRunning ? 2 : 1.5;
            const opacity = isEdgeSel ? 1 : nodeInvolved ? 0.9 : isRunning ? 0.85 : 0.45;
            const marker = isEdgeSel ? 'url(#arrow-sel)' : isRunning ? 'url(#arrow-run)' : 'url(#arrow-dim)';

            return (
              <g key={edge.id}>
                {/* Invisible wide hit area */}
                <path
                  d={d}
                  stroke="transparent" strokeWidth={18} fill="none"
                  style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                  onClick={(e) => { e.stopPropagation(); onSelectEdge(edge.id); onSelectNode(null); }}
                />
                {/* Visual edge */}
                {isRunning ? (
                  <path
                    d={d}
                    stroke={stroke} strokeWidth={strokeW} fill="none"
                    strokeDasharray="10 6"
                    opacity={opacity}
                    markerEnd={marker}
                    style={{ pointerEvents: 'none', animation: 'flowDash 0.5s linear infinite' }}
                  />
                ) : (
                  <path
                    d={d}
                    stroke={stroke} strokeWidth={strokeW} fill="none"
                    opacity={opacity}
                    markerEnd={marker}
                    style={{ pointerEvents: 'none', transition: 'stroke 0.2s, opacity 0.2s' }}
                  />
                )}
                {/* Selected highlight glow */}
                {isEdgeSel && (
                  <path d={d} stroke="var(--accent)" strokeWidth={6} fill="none" opacity={0.15} style={{ pointerEvents: 'none' }} />
                )}
              </g>
            );
          })}

          {/* Live connecting wire */}
          {connecting && (() => {
            const src = nodes.find(n => n.id === connecting.sourceId);
            if (!src) return null;
            const p1 = getPortPos(src, 'output', connecting.sourcePortIdx);
            const endX = snapTarget ? snapTarget.x : mousePos.x;
            const endY = snapTarget ? snapTarget.y : mousePos.y;
            return (
              <>
                <path
                  d={getBezier(p1.x, p1.y, endX, endY)}
                  stroke="var(--accent)" strokeWidth={2} fill="none"
                  strokeDasharray="8 5" opacity={0.9}
                  style={{ pointerEvents: 'none', animation: 'flowDash 0.4s linear infinite' }}
                />
                {snapTarget && (
                  <circle cx={snapTarget.x} cy={snapTarget.y} r={10} fill="var(--accent)" opacity={0.25} />
                )}
              </>
            );
          })()}
        </svg>

        {/* Nodes */}
        {nodes.map(node => (
          <CanvasNode
            key={node.id}
            node={node}
            selected={selectedId === node.id}
            runningNodeId={runningNodeId}
            connecting={!!connecting}
            onStartDrag={startDrag}
            onSelect={(id) => { onSelectNode(id); onSelectEdge(null); }}
            onStartConnect={startConnect}
            onEndConnect={endConnect}
            onClickInputPort={clickInputPort}
          />
        ))}
      </div>

      {/* Mini-map */}
      <MiniMap nodes={nodes} pan={pan} zoom={zoom} />

      {/* Zoom controls */}
      <ZoomControls zoom={zoom} setZoom={setZoom} setPan={setPan} />

      {/* Edge delete hint */}
      {selectedEdgeId && (
        <div style={{ position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)', background: 'var(--card)', border: '1px solid var(--accent)', borderRadius: 99, padding: '4px 14px', fontSize: 11, color: 'var(--text-muted)', pointerEvents: 'none', animation: 'fadeIn 0.2s ease' }}>
          Press <strong style={{ color: 'var(--text)' }}>Delete</strong> to remove connection
        </div>
      )}
    </div>
  );
}

// ─── Canvas Node ──────────────────────────────────────────────────────────────
function CanvasNode({ node, selected, runningNodeId, connecting, onStartDrag, onSelect, onStartConnect, onEndConnect, onClickInputPort }) {
  const def = NODE_REGISTRY[node.type];
  if (!def) return null;
  const catMeta = CATEGORY_META[def.cat];
  const isRunning = runningNodeId === node.id;
  const statusColor = {
    success: 'var(--success)', error: 'var(--error)', running: 'var(--running)', idle: 'transparent'
  }[node.status] || 'transparent';

  const maxPorts = Math.max(def.inputs.length, def.outputs.length, 1);

  const nodeStyle = {
    position: 'absolute', left: node.x, top: node.y, width: NODE_WIDTH,
    background: 'var(--card)',
    border: `1px solid ${selected ? 'var(--accent)' : 'var(--border)'}`,
    borderRadius: 10,
    boxShadow: selected ? `0 0 0 2.5px var(--accent-glow), var(--shadow)` : 'var(--shadow)',
    userSelect: 'none',
    transition: 'border-color 0.15s, box-shadow 0.15s',
    cursor: 'default',
    zIndex: selected ? 10 : 1,
  };
  const headerStyle = {
    display: 'flex', alignItems: 'center', gap: 7, padding: '8px 10px',
    borderBottom: '1px solid var(--border)', cursor: 'grab',
    borderRadius: '9px 9px 0 0',
    background: selected ? `${catMeta.color}15` : 'transparent',
    transition: 'background 0.15s',
  };

  return (
    <div
      style={nodeStyle}
      className={isRunning ? 'node-running' : ''}
      onMouseDown={e => { e.stopPropagation(); onSelect(node.id); }}
    >
      {/* Status bar top */}
      {node.status !== 'idle' && (
        <div style={{ position: 'absolute', top: 0, left: 10, right: 10, height: 2, background: statusColor, borderRadius: '0 0 4px 4px', zIndex: 3, transition: 'background 0.3s' }} />
      )}

      <div style={headerStyle} onMouseDown={e => { e.stopPropagation(); onSelect(node.id); onStartDrag(e, node.id); }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: catMeta.color, flexShrink: 0 }}></div>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', flex: 1, lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{def.label}</span>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: node.status === 'idle' ? 'transparent' : statusColor, border: node.status === 'idle' ? '1.5px solid var(--border2)' : 'none', transition: 'background 0.3s', flexShrink: 0 }}></div>
      </div>

      <div style={{ padding: '4px 0', minHeight: 26 }}>
        {Array.from({ length: maxPorts }).map((_, i) => {
          const inp = def.inputs[i];
          const out = def.outputs[i];
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', height: 26, position: 'relative' }}>
              {inp !== undefined && (
                <>
                  <PortDot
                    type="input" color={catMeta.color}
                    style={{ position: 'absolute', left: -(PORT_R + 1), top: '50%', transform: 'translateY(-50%)' }}
                    onMouseDown={e => onClickInputPort(e, node.id, i)}
                    onMouseUp={e => onEndConnect(e, node.id, i)}
                    accepting={connecting}
                    canDelete={!connecting}
                  />
                  <span style={{ marginLeft: 14, fontSize: 10.5, color: 'var(--text-muted)' }}>{inp}</span>
                </>
              )}
              {out !== undefined && (
                <>
                  <span style={{ marginLeft: 'auto', marginRight: 14, fontSize: 10.5, color: 'var(--text-muted)' }}>{out}</span>
                  <PortDot
                    type="output" color={catMeta.color}
                    style={{ position: 'absolute', right: -(PORT_R + 1), top: '50%', transform: 'translateY(-50%)' }}
                    onMouseDown={e => { e.stopPropagation(); e.preventDefault(); onStartConnect(e, node.id, i); }}
                  />
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PortDot({ type, color, style, onMouseDown, onMouseUp, accepting, canDelete }) {
  const [hov, setHov] = useStateC(false);
  const isInput = type === 'input';
  const portStyle = {
    ...style,
    width: PORT_R * 2, height: PORT_R * 2,
    borderRadius: '50%',
    background: hov ? color : 'var(--panel)',
    border: `2px solid ${(hov || (isInput && accepting)) ? color : 'var(--border2)'}`,
    cursor: type === 'output' ? 'crosshair' : (accepting ? 'cell' : (canDelete ? 'pointer' : 'default')),
    transition: 'all 0.12s',
    boxShadow: hov ? `0 0 10px ${color}90` : 'none',
    zIndex: 2,
  };
  return (
    <div
      style={portStyle}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      title={isInput && canDelete ? 'Click to remove connection' : undefined}
    />
  );
}

// ─── Mini Map ─────────────────────────────────────────────────────────────────
function MiniMap({ nodes, pan, zoom }) {
  const W = 140, H = 88;
  // Map world coords → mini-map coords
  const WORLD_W = 3000, WORLD_H = 2000;
  const sx = W / WORLD_W, sy = H / WORLD_H;
  // Viewport rect
  const vpW = (W / zoom) * sx * zoom * (WORLD_W / W);
  return (
    <div style={{ position: 'absolute', bottom: 56, right: 12, width: W, height: H, background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', opacity: 0.9 }}>
      <svg width={W} height={H}>
        {nodes.map(n => {
          const def = NODE_REGISTRY[n.type];
          const c = def ? CATEGORY_META[def.cat]?.color : 'var(--accent)';
          return (
            <rect key={n.id}
              x={n.x * sx} y={n.y * sy}
              width={Math.max(NODE_WIDTH * sx, 3)} height={Math.max(30 * sy, 2)}
              rx={2} fill={c || '#888'} opacity={0.7}
            />
          );
        })}
        {/* Viewport indicator */}
        <rect
          x={-pan.x / zoom * sx} y={-pan.y / zoom * sy}
          width={W / zoom * sx * WORLD_W / W * sx * WORLD_W / 30}
          height={H / zoom * sy * WORLD_H / H * sy * WORLD_H / 30}
          fill="none" stroke="var(--accent)" strokeWidth={1.5} rx={3} opacity={0.5}
        />
      </svg>
    </div>
  );
}

// ─── Zoom Controls ────────────────────────────────────────────────────────────
function ZoomControls({ zoom, setZoom, setPan }) {
  const btn = {
    width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)',
    background: 'var(--panel)', color: 'var(--text)', cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16,
  };
  const reset = () => { setZoom(1); setPan({ x: 120, y: 60 }); };
  return (
    <div style={{ position: 'absolute', bottom: 12, right: 12, display: 'flex', gap: 4, alignItems: 'center' }}>
      <button style={btn} onClick={() => setZoom(z => Math.max(0.2, +(z - 0.1).toFixed(2)))}>−</button>
      <span
        onClick={reset}
        style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 38, textAlign: 'center', cursor: 'pointer', fontVariantNumeric: 'tabular-nums' }}
        title="Reset view"
      >{Math.round(zoom * 100)}%</span>
      <button style={btn} onClick={() => setZoom(z => Math.min(2.5, +(z + 0.1).toFixed(2)))}>+</button>
    </div>
  );
}

Object.assign(window, { GraphCanvas });
