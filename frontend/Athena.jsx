// Main App — top bar, layout, state management, pipeline execution

const { useState, useEffect, useRef, useCallback } = React;

// ─── Initial pipeline (Classification Starter) ─────────────────────────────
const STARTER_NODES = [
  { id: 'n1', type: 'csv_loader',  x: 60,  y: 80,  status: 'idle', config: { path: 'data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 'n2', type: 'imputer',     x: 340, y: 60,  status: 'idle', config: { strategy: 'mean', fill_value: '0', cols: '' } },
  { id: 'n3', type: 'scaler',      x: 340, y: 200, status: 'idle', config: { method: 'StandardScaler', cols: '' } },
  { id: 'n4', type: 'train_test',  x: 620, y: 80,  status: 'idle', config: { test_size: 0.2, random_state: 42, stratify: true } },
  { id: 'n5', type: 'rf',          x: 900, y: 60,  status: 'idle', config: { n_estimators: 100, max_depth: 10, max_features: 'sqrt', random_state: 42 } },
  { id: 'n6', type: 'metrics',     x: 1180, y: 60, status: 'idle', config: { task: 'classification', average: 'weighted' } },
  { id: 'n7', type: 'conf_matrix', x: 1180, y: 200,status: 'idle', config: { normalize: 'none', cmap: 'Blues' } },
];
const STARTER_EDGES = [
  { id: 'e1', sourceId: 'n1', sourcePortIdx: 0, targetId: 'n2', targetPortIdx: 0 },
  { id: 'e2', sourceId: 'n2', sourcePortIdx: 0, targetId: 'n3', targetPortIdx: 0 },
  { id: 'e3', sourceId: 'n3', sourcePortIdx: 0, targetId: 'n4', targetPortIdx: 0 },
  { id: 'e4', sourceId: 'n4', sourcePortIdx: 0, targetId: 'n5', targetPortIdx: 0 },
  { id: 'e5', sourceId: 'n4', sourcePortIdx: 1, targetId: 'n6', targetPortIdx: 1 },
  { id: 'e6', sourceId: 'n5', sourcePortIdx: 0, targetId: 'n6', targetPortIdx: 0 },
  { id: 'e7', sourceId: 'n5', sourcePortIdx: 0, targetId: 'n7', targetPortIdx: 0 },
  { id: 'e8', sourceId: 'n4', sourcePortIdx: 1, targetId: 'n7', targetPortIdx: 1 },
];

const TEMPLATES = {
  classification: { nodes: STARTER_NODES, edges: STARTER_EDGES },
  regression: {
    nodes: [
      { id: 'r1', type: 'csv_loader', x: 60, y: 100, status: 'idle', config: {} },
      { id: 'r2', type: 'imputer', x: 320, y: 100, status: 'idle', config: { strategy: 'median' } },
      { id: 'r3', type: 'feat_gen', x: 580, y: 100, status: 'idle', config: { degree: 2 } },
      { id: 'r4', type: 'train_test', x: 840, y: 100, status: 'idle', config: {} },
      { id: 'r5', type: 'lin_reg', x: 1100, y: 80, status: 'idle', config: {} },
      { id: 'r6', type: 'metrics', x: 1360, y: 80, status: 'idle', config: { task: 'regression' } },
      { id: 'r7', type: 'residual', x: 1360, y: 220, status: 'idle', config: {} },
    ],
    edges: [
      { id: 're1', sourceId: 'r1', sourcePortIdx: 0, targetId: 'r2', targetPortIdx: 0 },
      { id: 're2', sourceId: 'r2', sourcePortIdx: 0, targetId: 'r3', targetPortIdx: 0 },
      { id: 're3', sourceId: 'r3', sourcePortIdx: 0, targetId: 'r4', targetPortIdx: 0 },
      { id: 're4', sourceId: 'r4', sourcePortIdx: 0, targetId: 'r5', targetPortIdx: 0 },
      { id: 're5', sourceId: 'r5', sourcePortIdx: 0, targetId: 'r6', targetPortIdx: 0 },
      { id: 're6', sourceId: 'r4', sourcePortIdx: 1, targetId: 'r6', targetPortIdx: 1 },
      { id: 're7', sourceId: 'r5', sourcePortIdx: 0, targetId: 'r7', targetPortIdx: 0 },
    ]
  },
  nlp: {
    nodes: [
      { id: 't1', type: 'csv_loader', x: 60, y: 100, status: 'idle', config: {} },
      { id: 't2', type: 'tfidf', x: 320, y: 100, status: 'idle', config: { col: 'text', method: 'TF-IDF', max_features: 5000 } },
      { id: 't3', type: 'train_test', x: 580, y: 100, status: 'idle', config: {} },
      { id: 't4', type: 'log_reg', x: 840, y: 80, status: 'idle', config: {} },
      { id: 't5', type: 'metrics', x: 1100, y: 80, status: 'idle', config: {} },
      { id: 't6', type: 'shap', x: 1100, y: 220, status: 'idle', config: {} },
    ],
    edges: [
      { id: 'te1', sourceId: 't1', sourcePortIdx: 0, targetId: 't2', targetPortIdx: 0 },
      { id: 'te2', sourceId: 't2', sourcePortIdx: 0, targetId: 't3', targetPortIdx: 0 },
      { id: 'te3', sourceId: 't3', sourcePortIdx: 0, targetId: 't4', targetPortIdx: 0 },
      { id: 'te4', sourceId: 't4', sourcePortIdx: 0, targetId: 't5', targetPortIdx: 0 },
      { id: 'te5', sourceId: 't3', sourcePortIdx: 1, targetId: 't5', targetPortIdx: 1 },
      { id: 'te6', sourceId: 't4', sourcePortIdx: 0, targetId: 't6', targetPortIdx: 0 },
    ]
  }
};

let nodeCounter = 100;

function App() {
  const [theme, setTheme] = useState('dark');
  const [nodes, setNodes] = useState(STARTER_NODES);
  const [edges, setEdges] = useState(STARTER_EDGES);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | running | completed | error
  const [runningNodeId, setRunningNodeId] = useState(null);
  const [showExport, setShowExport] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [toast, setToast] = useState(null);
  const [history, setHistory] = useState([{ nodes: STARTER_NODES, edges: STARTER_EDGES }]);
  const [histIdx, setHistIdx] = useState(0);
  const runRef = useRef(false);

  // Theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Keyboard shortcuts — only undo/redo here; Delete/Escape handled in GraphCanvas
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); handleUndo(); }
      if ((e.metaKey || e.ctrlKey) && (e.key === 'y' || (e.shiftKey && e.key === 'z'))) { e.preventDefault(); handleRedo(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [histIdx, history]);

  const pushHistory = (ns, es) => {
    const next = [...history.slice(0, histIdx + 1), { nodes: ns, edges: es }];
    setHistory(next); setHistIdx(next.length - 1);
  };
  const handleUndo = () => { if (histIdx > 0) { const h = history[histIdx - 1]; setNodes(h.nodes); setEdges(h.edges); setHistIdx(i => i - 1); } };
  const handleRedo = () => { if (histIdx < history.length - 1) { const h = history[histIdx + 1]; setNodes(h.nodes); setEdges(h.edges); setHistIdx(i => i + 1); } };

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2800);
  };

  const deleteNode = (id) => {
    const ns = nodes.filter(n => n.id !== id);
    const es = edges.filter(e => e.sourceId !== id && e.targetId !== id);
    setNodes(ns); setEdges(es); setSelectedId(null);
    pushHistory(ns, es);
  };

  // Topological sort for execution order
  const topoSort = (ns, es) => {
    const inDeg = {};
    ns.forEach(n => inDeg[n.id] = 0);
    es.forEach(e => { inDeg[e.targetId] = (inDeg[e.targetId] || 0) + 1; });
    const queue = ns.filter(n => inDeg[n.id] === 0);
    const order = [];
    while (queue.length) {
      const node = queue.shift();
      order.push(node.id);
      es.filter(e => e.sourceId === node.id).forEach(e => {
        inDeg[e.targetId]--;
        if (inDeg[e.targetId] === 0) queue.push(ns.find(n => n.id === e.targetId));
      });
    }
    return order;
  };

  const runPipeline = async () => {
    if (status === 'running') return;
    runRef.current = true;
    setStatus('running');
    setNodes(prev => prev.map(n => ({ ...n, status: 'idle' })));
    showToast('Pipeline started…', 'info');
    const order = topoSort(nodes, edges);
    for (let i = 0; i < order.length; i++) {
      if (!runRef.current) break;
      const id = order[i];
      setRunningNodeId(id);
      setNodes(prev => prev.map(n => n.id === id ? { ...n, status: 'running' } : n));
      await new Promise(r => setTimeout(r, 600 + Math.random() * 600));
      const fail = Math.random() < 0.04;
      setNodes(prev => prev.map(n => n.id === id ? { ...n, status: fail ? 'error' : 'success' } : n));
      if (fail) { setStatus('error'); setRunningNodeId(null); showToast(`Error at node ${id}`, 'error'); runRef.current = false; return; }
    }
    setRunningNodeId(null);
    setStatus('completed');
    showToast('Pipeline completed successfully!', 'success');
  };

  const stopPipeline = () => { runRef.current = false; setStatus('idle'); setRunningNodeId(null); setNodes(prev => prev.map(n => ({ ...n, status: 'idle' }))); showToast('Pipeline stopped', 'warn'); };

  const handleDragStart = (e, type) => { e.dataTransfer.setData('nodeType', type); };

  const handleDropNode = (type, x, y) => {
    const def = NODE_REGISTRY[type];
    if (!def) return;
    const defaultConfig = {};
    (def.config || []).forEach(f => defaultConfig[f.id] = f.default);
    const newNode = { id: `n_${++nodeCounter}`, type, x, y, status: 'idle', config: defaultConfig };
    const ns = [...nodes, newNode];
    setNodes(ns); pushHistory(ns, edges);
  };

  const handleNodeConfigChange = (nodeId, config) => {
    setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, config } : n));
  };

  const loadTemplate = (key) => {
    const t = TEMPLATES[key];
    if (!t) return;
    setNodes(t.nodes); setEdges(t.edges); setSelectedId(null);
    pushHistory(t.nodes, t.edges);
    setShowTemplates(false);
    showToast(`Loaded ${key} template`, 'success');
  };

  const selectedNode = nodes.find(n => n.id === selectedId) || null;
  const sidebarVisible = !!selectedNode;

  const appStyle = { display: 'flex', flexDirection: 'column', width: '100%', height: '100%', overflow: 'hidden' };
  const mainStyle = { display: 'flex', flex: 1, overflow: 'hidden' };

  // Sidebar slide wrapper — animates width + translateX
  const sidebarWrapStyle = {
    width: sidebarVisible ? 280 : 0,
    minWidth: 0,
    overflow: 'hidden',
    transition: 'width 0.28s cubic-bezier(0.4, 0, 0.2, 1)',
    flexShrink: 0,
    position: 'relative',
  };
  const sidebarInnerStyle = {
    width: 280,
    height: '100%',
    transform: sidebarVisible ? 'translateX(0)' : 'translateX(100%)',
    transition: 'transform 0.28s cubic-bezier(0.4, 0, 0.2, 1)',
  };

  return (
    <div style={appStyle}>
      <TopBar
        status={status}
        theme={theme}
        onToggleTheme={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
        onRun={runPipeline}
        onStop={stopPipeline}
        onUndo={handleUndo}
        onRedo={handleRedo}
        canUndo={histIdx > 0}
        canRedo={histIdx < history.length - 1}
        onShowExport={() => setShowExport(true)}
        onShowTemplates={() => setShowTemplates(true)}
        onSave={() => showToast('Pipeline saved', 'success')}
        nodeCount={nodes.length}
        edgeCount={edges.length}
      />
      <div style={mainStyle}>
        <LeftSidebar onDragStart={handleDragStart} />
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          selectedId={selectedId}
          selectedEdgeId={selectedEdgeId}
          status={status}
          runningNodeId={runningNodeId}
          onNodesChange={setNodes}
          onEdgesChange={setEdges}
          onSelectNode={setSelectedId}
          onSelectEdge={setSelectedEdgeId}
          onDropNode={handleDropNode}
        />
        <div style={sidebarWrapStyle}>
          <div style={sidebarInnerStyle}>
            <RightSidebar
              selectedNode={selectedNode}
              onNodeConfigChange={handleNodeConfigChange}
            />
          </div>
        </div>
      </div>
      {toast && <Toast msg={toast.msg} type={toast.type} />}
      {showExport && <ExportModal onClose={() => setShowExport(false)} onExport={(fmt) => { setShowExport(false); showToast(`Exported as ${fmt}`, 'success'); }} />}
      {showTemplates && <TemplatesModal onClose={() => setShowTemplates(false)} onLoad={loadTemplate} />}
    </div>
  );
}

// ─── Top Bar ─────────────────────────────────────────────────────────────────
function TopBar({ status, theme, onToggleTheme, onRun, onStop, onUndo, onRedo, canUndo, canRedo, onShowExport, onShowTemplates, onSave, nodeCount, edgeCount }) {
  const barStyle = {
    height: 48, flexShrink: 0,
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '0 14px',
    background: 'var(--panel)',
    borderBottom: '1px solid var(--border)',
    zIndex: 100,
  };
  const divStyle = { width: 1, height: 20, background: 'var(--border)', margin: '0 4px', flexShrink: 0 };

  const STATUS_CONFIG = {
    idle:      { color: 'var(--text-muted)', label: 'Idle',      dot: 'var(--text-muted)' },
    running:   { color: 'var(--running)',    label: 'Running…',  dot: 'var(--running)' },
    completed: { color: 'var(--success)',    label: 'Completed', dot: 'var(--success)' },
    error:     { color: 'var(--error)',      label: 'Error',     dot: 'var(--error)' },
  };
  const sc = STATUS_CONFIG[status];

  return (
    <div style={barStyle}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 8 }}>
        <div style={{ width: 26, height: 26, borderRadius: 7, background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <polygon points="7,1 13,4.5 13,9.5 7,13 1,9.5 1,4.5" stroke="white" strokeWidth="1.5" fill="none"/>
            <circle cx="7" cy="7" r="2" fill="white"/>
          </svg>
        </div>
        <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)' }}>Athena</span>
      </div>

      <div style={divStyle}></div>

      {/* Pipeline actions */}
      <Btn onClick={onRun} disabled={status === 'running'} primary>
        {status === 'running' ? <span className="spin" style={{ display: 'inline-block' }}>↻</span> : '▶'} Run
      </Btn>
      <Btn onClick={onStop} disabled={status !== 'running'}>⏹ Stop</Btn>

      <div style={divStyle}></div>

      <Btn onClick={onUndo} disabled={!canUndo} title="Undo (⌘Z)">↩</Btn>
      <Btn onClick={onRedo} disabled={!canRedo} title="Redo (⌘⇧Z)">↪</Btn>

      <div style={divStyle}></div>

      <Btn onClick={onSave}>Save</Btn>
      <Btn onClick={onShowTemplates}>Templates</Btn>
      <Btn onClick={onShowExport}>Export Code</Btn>

      {/* Spacer */}
      <div style={{ flex: 1 }}></div>

      {/* Stats */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10, marginRight: 8 }}>
        <span>{nodeCount} nodes</span>
        <span>{edgeCount} edges</span>
      </div>

      {/* Status indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: 'var(--card)', borderRadius: 99, border: '1px solid var(--border)' }}>
        <div style={{ width: 6, height: 6, borderRadius: '50%', background: sc.dot }} className={status === 'running' ? 'status-running' : ''}></div>
        <span style={{ fontSize: 11, fontWeight: 500, color: sc.color }}>{sc.label}</span>
      </div>

      <div style={divStyle}></div>

      {/* Theme toggle */}
      <button onClick={onToggleTheme} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', cursor: 'pointer', padding: '5px 8px', fontSize: 14, lineHeight: 1 }} title="Toggle theme">
        {theme === 'dark' ? '☀' : '◑'}
      </button>
    </div>
  );
}

function Btn({ children, onClick, disabled, primary, title }) {
  const [hov, setHov] = useState(false);
  const style = {
    display: 'flex', alignItems: 'center', gap: 5,
    padding: '5px 11px', borderRadius: 6, border: '1px solid',
    fontSize: 12, fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'var(--font)', lineHeight: 1, transition: 'all 0.15s',
    background: primary ? (hov && !disabled ? 'oklch(74% 0.22 225)' : 'var(--accent)') : (hov && !disabled ? 'var(--card2)' : 'var(--card)'),
    color: primary ? 'white' : (disabled ? 'var(--text-muted)' : 'var(--text)'),
    borderColor: primary ? 'transparent' : (disabled ? 'var(--border)' : hov ? 'var(--border2)' : 'var(--border)'),
    opacity: disabled ? 0.5 : 1,
  };
  return (
    <button style={style} onClick={disabled ? undefined : onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} title={title}>
      {children}
    </button>
  );
}

// ─── Toast ───────────────────────────────────────────────────────────────────
function Toast({ msg, type }) {
  const colors = { info: 'var(--accent)', success: 'var(--success)', error: 'var(--error)', warn: 'var(--warning)' };
  const style = {
    position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
    background: 'var(--card)', border: `1px solid ${colors[type] || 'var(--border)'}`,
    borderRadius: 8, padding: '9px 18px', display: 'flex', alignItems: 'center', gap: 8,
    boxShadow: 'var(--shadow-lg)', zIndex: 9999, fontSize: 13,
    animation: 'fadeIn 0.2s ease',
  };
  return (
    <div style={style}>
      <div style={{ width: 7, height: 7, borderRadius: '50%', background: colors[type], flexShrink: 0 }}></div>
      <span style={{ color: 'var(--text)' }}>{msg}</span>
    </div>
  );
}

// ─── Export Modal ─────────────────────────────────────────────────────────────
function ExportModal({ onClose, onExport }) {
  const overlayStyle = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' };
  const modalStyle = { background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 420, boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' };
  const headerStyle = { padding: '18px 20px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' };
  const titleStyle = { fontSize: 14, fontWeight: 700, color: 'var(--text)' };
  const bodyStyle = { padding: 20, display: 'flex', flexDirection: 'column', gap: 10 };

  const formats = [
    { id: 'Python Script', icon: '🐍', desc: 'Clean pandas + scikit-learn code' },
    { id: 'Jupyter Notebook', icon: '📓', desc: 'Interactive .ipynb with cells' },
    { id: 'Pipeline JSON', icon: '⚙', desc: 'Serialized pipeline configuration' },
    { id: 'Trained Model (.pkl)', icon: '💾', desc: 'Download serialized model file' },
  ];

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={modalStyle} onClick={e => e.stopPropagation()}>
        <div style={headerStyle}>
          <div style={titleStyle}>Export Pipeline</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>×</button>
        </div>
        <div style={bodyStyle}>
          {formats.map(f => (
            <div key={f.id} onClick={() => onExport(f.id)} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', cursor: 'pointer', transition: 'all 0.15s' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--card)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <span style={{ fontSize: 20 }}>{f.icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{f.id}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{f.desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 14 }}>↓</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Templates Modal ──────────────────────────────────────────────────────────
function TemplatesModal({ onClose, onLoad }) {
  const overlayStyle = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' };
  const modalStyle = { background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 14, width: 440, boxShadow: 'var(--shadow-lg)', animation: 'fadeIn 0.18s ease' };
  const headerStyle = { padding: '18px 20px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' };
  const bodyStyle = { padding: 20, display: 'flex', flexDirection: 'column', gap: 10 };

  const templates = [
    { id: 'classification', label: 'Classification Starter', desc: 'CSV → Imputer → Scaler → Train/Test → Random Forest → Metrics + Confusion Matrix', nodes: 7 },
    { id: 'regression', label: 'Regression Pipeline', desc: 'CSV → Imputer → Feature Gen → Train/Test → Linear Regression → Metrics + Residuals', nodes: 7 },
    { id: 'nlp', label: 'NLP Pipeline', desc: 'CSV → TF-IDF Vectorizer → Train/Test → Logistic Regression → Metrics + SHAP', nodes: 6 },
  ];

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={modalStyle} onClick={e => e.stopPropagation()}>
        <div style={headerStyle}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Pipeline Templates</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>×</button>
        </div>
        <div style={bodyStyle}>
          {templates.map(t => (
            <div key={t.id} onClick={() => onLoad(t.id)} style={{ padding: '12px 14px', borderRadius: 8, border: '1px solid var(--border)', cursor: 'pointer', transition: 'all 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--card)'; e.currentTarget.style.borderColor = 'var(--accent)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'var(--border)'; }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{t.label}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', background: 'var(--card2)', padding: '2px 7px', borderRadius: 99 }}>{t.nodes} nodes</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{t.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
