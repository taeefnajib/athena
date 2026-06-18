// Inspector Panel — right sidebar with tabs, config, data preview, logs, metrics

const { useState: useStateI, useEffect: useEffectI, useRef: useRefI } = React;

const MOCK_METRICS = {
  accuracy: 0.9234, precision: 0.9187, recall: 0.9301, f1: 0.9244,
  roc_auc: 0.9712, rmse: 0.0412, mae: 0.0318, r2: 0.8876,
};
const MOCK_LOGS = [
  { t: '14:02:31', level: 'info',  msg: 'Node initialized' },
  { t: '14:02:32', level: 'info',  msg: 'Loading data…' },
  { t: '14:02:33', level: 'info',  msg: 'Parsed 1,240 rows × 14 columns' },
  { t: '14:02:33', level: 'warn',  msg: '3 columns have >5% missing values' },
  { t: '14:02:34', level: 'info',  msg: 'Execution complete in 1.34s' },
  { t: '14:02:34', level: 'success', msg: 'Output: dataset (1,240 × 14)' },
];
const MOCK_PREVIEW = {
  cols: ['age', 'income', 'category', 'score', 'label'],
  rows: [
    [34, 62000, 'A', 0.82, 1],
    [45, 88000, 'B', 0.61, 0],
    [28, 41000, 'A', 0.77, 1],
    [52, 105000, 'C', 0.44, 0],
    [31, 57000, 'B', 0.91, 1],
    [67, 130000, 'A', 0.38, 0],
    [23, 34000, 'C', 0.55, 1],
  ]
};

function RightSidebar({ selectedNode, onNodeConfigChange }) {
  const [tab, setTab] = useStateI('settings');
  const def = selectedNode ? NODE_REGISTRY[selectedNode.type] : null;
  const catMeta = def ? CATEGORY_META[def.cat] : null;

  const sideStyle = {
    width: 280, minWidth: 280,
    background: 'var(--panel)',
    borderLeft: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column',
    height: '100%', overflow: 'hidden',
  };

  if (!selectedNode) {
    return (
      <div style={sideStyle}>
        <EmptyInspector />
      </div>
    );
  }

  return (
    <div style={sideStyle}>
      {/* Node header */}
      <NodeHeader def={def} catMeta={catMeta} node={selectedNode} />
      {/* Tabs */}
      <TabBar tab={tab} setTab={setTab} />
      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {tab === 'settings' && <SettingsTab def={def} node={selectedNode} onChange={onNodeConfigChange} />}
        {tab === 'preview'  && <PreviewTab />}
        {tab === 'logs'     && <LogsTab node={selectedNode} />}
        {tab === 'metrics'  && <MetricsTab def={def} />}
      </div>
    </div>
  );
}

function EmptyInspector() {
  const style = {
    flex: 1, display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center', gap: 10,
    padding: 24, color: 'var(--text-muted)',
  };
  return (
    <div style={style}>
      <div style={{ fontSize: 32, opacity: 0.3 }}>◎</div>
      <div style={{ fontSize: 12, textAlign: 'center', lineHeight: 1.6 }}>
        Select a node to inspect its settings, preview data, and view logs.
      </div>
    </div>
  );
}

function NodeHeader({ def, catMeta, node }) {
  const style = {
    padding: '14px 16px 12px',
    borderBottom: '1px solid var(--border)',
    background: `linear-gradient(135deg, ${catMeta.color}18, transparent)`,
  };
  const badgeStyle = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    padding: '2px 8px', borderRadius: 99,
    background: `${catMeta.color}20`,
    border: `1px solid ${catMeta.color}40`,
    fontSize: 10, fontWeight: 600, letterSpacing: '0.04em',
    color: catMeta.color, marginBottom: 6,
  };
  const statusMap = { idle: { color: 'var(--text-muted)', label: 'Idle' }, running: { color: 'var(--running)', label: 'Running…' }, success: { color: 'var(--success)', label: 'Complete' }, error: { color: 'var(--error)', label: 'Error' } };
  const st = statusMap[node.status || 'idle'];
  return (
    <div style={style}>
      <div style={badgeStyle}>
        <span>{catMeta.icon}</span>
        <span>{catMeta.label}</span>
      </div>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>{def.label}</div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 8 }}>{def.desc}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <div style={{ width: 6, height: 6, borderRadius: '50%', background: st.color }}></div>
        <span style={{ fontSize: 11, color: st.color }}>{st.label}</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>{node.id.slice(0,8)}</span>
      </div>
    </div>
  );
}

function TabBar({ tab, setTab }) {
  const TABS = [
    { id: 'settings', label: 'Settings' },
    { id: 'preview',  label: 'Preview' },
    { id: 'logs',     label: 'Logs' },
    { id: 'metrics',  label: 'Metrics' },
  ];
  const barStyle = {
    display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0,
  };
  const tabStyle = (active) => ({
    flex: 1, padding: '8px 4px', textAlign: 'center',
    fontSize: 11, fontWeight: active ? 600 : 400,
    color: active ? 'var(--accent)' : 'var(--text-muted)',
    cursor: 'pointer', borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
    marginBottom: -1, transition: 'color 0.15s',
  });
  return (
    <div style={barStyle}>
      {TABS.map(t => <div key={t.id} style={tabStyle(tab === t.id)} onClick={() => setTab(t.id)}>{t.label}</div>)}
    </div>
  );
}

// ─── Settings Tab ────────────────────────────────────────────────────────────
function SettingsTab({ def, node, onChange }) {
  const config = node.config || {};
  const sectionStyle = { padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 };
  const fieldStyle = { display: 'flex', flexDirection: 'column', gap: 4 };
  const labelStyle = { fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', letterSpacing: '0.02em' };
  const inputBase = {
    background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text)', fontSize: 12, padding: '6px 10px',
    outline: 'none', fontFamily: 'var(--font)', width: '100%',
    transition: 'border-color 0.15s',
  };
  const taStyle = { ...inputBase, resize: 'vertical', minHeight: 72, fontFamily: 'var(--mono)', fontSize: 11 };

  if (!def.config || def.config.length === 0) {
    return (
      <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 12 }}>
        No configurable parameters for this node.
      </div>
    );
  }

  return (
    <div style={sectionStyle}>
      {def.config.map(field => {
        const val = config[field.id] !== undefined ? config[field.id] : field.default;
        const update = v => onChange(node.id, { ...config, [field.id]: v });
        return (
          <div key={field.id} style={fieldStyle}>
            <label style={labelStyle}>{field.label}</label>
            {field.type === 'text' && (
              <input style={inputBase} value={val} onChange={e => update(e.target.value)} />
            )}
            {field.type === 'number' && (
              <input style={inputBase} type="number" value={val} onChange={e => update(Number(e.target.value))} />
            )}
            {field.type === 'select' && (
              <select style={{ ...inputBase, cursor: 'pointer' }} value={val} onChange={e => update(e.target.value)}>
                {field.options.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {field.type === 'toggle' && (
              <Toggle value={val} onChange={update} />
            )}
            {field.type === 'textarea' && (
              <textarea style={taStyle} value={val} onChange={e => update(e.target.value)} rows={4} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function Toggle({ value, onChange }) {
  const trackStyle = {
    width: 34, height: 18, borderRadius: 99,
    background: value ? 'var(--accent)' : 'var(--card2)',
    border: '1px solid var(--border2)',
    position: 'relative', cursor: 'pointer', transition: 'background 0.2s',
    flexShrink: 0,
  };
  const thumbStyle = {
    position: 'absolute', top: 2,
    left: value ? 15 : 2,
    width: 12, height: 12, borderRadius: '50%',
    background: 'white', transition: 'left 0.2s',
    boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={trackStyle} onClick={() => onChange(!value)}>
        <div style={thumbStyle}></div>
      </div>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{value ? 'Enabled' : 'Disabled'}</span>
    </div>
  );
}

// ─── Preview Tab ─────────────────────────────────────────────────────────────
function PreviewTab() {
  const wrapStyle = { padding: 12, overflowX: 'auto' };
  const summaryStyle = { fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, display: 'flex', gap: 12 };
  const tableStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 11 };
  const thStyle = { textAlign: 'left', padding: '5px 8px', background: 'var(--card2)', color: 'var(--text-dim)', fontWeight: 600, borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap', fontSize: 10.5 };
  const tdStyle = { padding: '4px 8px', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)', fontFamily: 'var(--mono)', fontSize: 11 };

  return (
    <div style={wrapStyle}>
      <div style={summaryStyle}>
        <span><strong style={{ color: 'var(--text)' }}>1,240</strong> rows</span>
        <span><strong style={{ color: 'var(--text)' }}>14</strong> cols</span>
        <span style={{ marginLeft: 'auto', color: 'var(--success)' }}>● Live</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={tableStyle}>
          <thead>
            <tr>{MOCK_PREVIEW.cols.map(c => <th key={c} style={thStyle}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {MOCK_PREVIEW.rows.map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--card)' }}>
                {row.map((cell, j) => <td key={j} style={tdStyle}>{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-muted)' }}>Showing 7 of 1,240 rows</div>
    </div>
  );
}

// ─── Logs Tab ────────────────────────────────────────────────────────────────
function LogsTab({ node }) {
  const logStyle = { padding: '8px 0', display: 'flex', flexDirection: 'column', gap: 1 };
  const levelColors = { info: 'var(--text-muted)', warn: 'var(--warning)', error: 'var(--error)', success: 'var(--success)' };
  const rowStyle = { display: 'flex', gap: 8, padding: '4px 14px', fontSize: 11 };

  const logs = node.status === 'idle' ? MOCK_LOGS.slice(0, 1) : MOCK_LOGS;

  return (
    <div style={logStyle}>
      {logs.map((l, i) => (
        <div key={i} style={{ ...rowStyle, background: i % 2 === 0 ? 'transparent' : 'var(--card)' }}>
          <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--mono)', flexShrink: 0 }}>{l.t}</span>
          <span style={{ color: levelColors[l.level], fontWeight: 600, textTransform: 'uppercase', fontSize: 9.5, flexShrink: 0, paddingTop: 1 }}>{l.level}</span>
          <span style={{ color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>{l.msg}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Metrics Tab ─────────────────────────────────────────────────────────────
function MetricsTab({ def }) {
  const isEval = ['eval', 'model', 'advanced'].includes(def?.cat);
  const wrapStyle = { padding: 16 };
  const gridStyle = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 };
  const cardStyle = (val) => ({
    background: 'var(--card)', borderRadius: 8, padding: '10px 12px',
    border: '1px solid var(--border)',
  });
  const valStyle = { fontSize: 22, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--text)', lineHeight: 1.2 };
  const lblStyle = { fontSize: 10, color: 'var(--text-muted)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.05em' };
  const barStyle = (val, color) => ({
    height: 4, borderRadius: 99, background: 'var(--card2)', marginTop: 6, overflow: 'hidden'
  });
  const fillStyle = (val, color) => ({
    height: '100%', width: `${val * 100}%`, borderRadius: 99,
    background: color || 'var(--accent)',
  });

  if (!isEval) {
    return (
      <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.7 }}>
        Run the pipeline to see performance metrics for this node.
      </div>
    );
  }

  const classMetrics = [
    { key: 'accuracy',  label: 'Accuracy',  val: MOCK_METRICS.accuracy, color: 'var(--accent)' },
    { key: 'f1',        label: 'F1 Score',  val: MOCK_METRICS.f1, color: 'var(--accent2)' },
    { key: 'precision', label: 'Precision', val: MOCK_METRICS.precision, color: 'var(--success)' },
    { key: 'recall',    label: 'Recall',    val: MOCK_METRICS.recall, color: 'var(--warning)' },
  ];

  return (
    <div style={wrapStyle}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Classification</div>
      <div style={gridStyle}>
        {classMetrics.map(m => (
          <div key={m.key} style={cardStyle(m.val)}>
            <div style={valStyle}>{(m.val * 100).toFixed(1)}<span style={{ fontSize: 13 }}>%</span></div>
            <div style={lblStyle}>{m.label}</div>
            <div style={barStyle()}><div style={fillStyle(m.val, m.color)}></div></div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>ROC-AUC</div>
      <div style={{ background: 'var(--card)', borderRadius: 8, padding: '10px 12px', border: '1px solid var(--border)' }}>
        <MiniRocCurve auc={MOCK_METRICS.roc_auc} />
      </div>
    </div>
  );
}

function MiniRocCurve({ auc }) {
  const pts = [[0,0],[0.05,0.42],[0.1,0.65],[0.2,0.82],[0.35,0.91],[0.5,0.95],[0.75,0.98],[1,1]];
  const W = 220, H = 100;
  const toSvg = ([x,y]) => [x * W, (1-y) * H];
  const path = pts.map((p,i) => `${i===0?'M':'L'}${toSvg(p).join(',')}`).join(' ');
  const fill = pts.map((p,i) => `${i===0?'M':'L'}${toSvg(p).join(',')}`).join(' ') + ` L${W},${H} L0,${H} Z`;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
        <line x1={0} y1={0} x2={W} y2={H} stroke="var(--border2)" strokeDasharray="4,3" strokeWidth={1} />
        <path d={fill} fill="var(--accent)" opacity={0.1} />
        <path d={path} stroke="var(--accent)" strokeWidth={2} fill="none" />
      </svg>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4, textAlign: 'center' }}>
        AUC = <strong style={{ color: 'var(--accent)' }}>{auc.toFixed(4)}</strong>
      </div>
    </div>
  );
}

Object.assign(window, { RightSidebar });
