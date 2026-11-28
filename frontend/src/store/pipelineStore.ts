import { create } from 'zustand'
import { groupNodes as groupSubflow, ungroupNode as ungroupSubflow } from '../lib/subflow'
import { NODE_REGISTRY } from '../registry/nodeRegistry'
import { DEFAULT_META, pickPolicy, type NodePolicy, type PipelineMeta, type PipelineSpec, type NodeStatus } from '../types/pipeline'

export interface PipelineNode {
  id: string
  type: string
  position: { x: number; y: number }
  config: Record<string, unknown>
  status: NodeStatus
  /** Execution policy (spec v2): timeout, retry, cache, runtime, resources. */
  policy?: NodePolicy
}

export interface PipelineEdge {
  id: string
  source: string
  target: string
  sourcePort: number
  targetPort: number
}

interface HistoryEntry { nodes: PipelineNode[]; edges: PipelineEdge[] }

const STARTER_NODES: PipelineNode[] = [
  { id: 'n1', type: 'csv_loader',  position: { x: 60,   y: 80  }, status: 'idle', config: { path: 'data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 'n2', type: 'imputer',     position: { x: 340,  y: 60  }, status: 'idle', config: { strategy: 'mean', fill_value: '0', cols: '' } },
  { id: 'n3', type: 'scaler',      position: { x: 340,  y: 200 }, status: 'idle', config: { method: 'StandardScaler', cols: '' } },
  { id: 'n4', type: 'train_test',  position: { x: 620,  y: 80  }, status: 'idle', config: { test_size: 0.2, random_state: 42, stratify: false } },
  { id: 'n5', type: 'rf',          position: { x: 900,  y: 60  }, status: 'idle', config: { n_estimators: 100, max_depth: 10, max_features: 'sqrt', random_state: 42 } },
  { id: 'n6', type: 'metrics',     position: { x: 1180, y: 60  }, status: 'idle', config: { task: 'classification', average: 'weighted' } },
  { id: 'n7', type: 'conf_matrix', position: { x: 1180, y: 200 }, status: 'idle', config: { normalize: 'none', cmap: 'Blues' } },
]
const STARTER_EDGES: PipelineEdge[] = [
  { id: 'e1',  source: 'n1', sourcePort: 0, target: 'n2', targetPort: 0 },
  { id: 'e2',  source: 'n2', sourcePort: 0, target: 'n3', targetPort: 0 },
  { id: 'e3',  source: 'n3', sourcePort: 0, target: 'n4', targetPort: 0 },
  { id: 'e4',  source: 'n4', sourcePort: 0, target: 'n5', targetPort: 0 }, // X_train → rf
  { id: 'e5',  source: 'n4', sourcePort: 1, target: 'n5', targetPort: 1 }, // y_train → rf
  { id: 'e6',  source: 'n5', sourcePort: 0, target: 'n6', targetPort: 0 }, // model → metrics
  { id: 'e7',  source: 'n4', sourcePort: 2, target: 'n6', targetPort: 1 }, // X_test → metrics
  { id: 'e8',  source: 'n4', sourcePort: 3, target: 'n6', targetPort: 2 }, // y_test → metrics
  { id: 'e9',  source: 'n5', sourcePort: 0, target: 'n7', targetPort: 0 }, // model → conf_matrix
  { id: 'e10', source: 'n4', sourcePort: 2, target: 'n7', targetPort: 1 }, // X_test → conf_matrix
  { id: 'e11', source: 'n4', sourcePort: 3, target: 'n7', targetPort: 2 }, // y_test → conf_matrix
]

const REGRESSION_NODES: PipelineNode[] = [
  { id: 'r1', type: 'csv_loader', position: { x: 60,   y: 100 }, status: 'idle', config: { path: 'regression_data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 'r2', type: 'imputer',    position: { x: 320,  y: 100 }, status: 'idle', config: { strategy: 'median' } },
  { id: 'r3', type: 'feat_gen',   position: { x: 580,  y: 100 }, status: 'idle', config: { degree: 2 } },
  { id: 'r4', type: 'train_test', position: { x: 840,  y: 100 }, status: 'idle', config: {} },
  { id: 'r5', type: 'lin_reg',    position: { x: 1100, y: 80  }, status: 'idle', config: {} },
  { id: 'r6', type: 'metrics',    position: { x: 1360, y: 80  }, status: 'idle', config: { task: 'regression' } },
  { id: 'r7', type: 'residual',   position: { x: 1360, y: 220 }, status: 'idle', config: {} },
]
const REGRESSION_EDGES: PipelineEdge[] = [
  { id: 're1',  source: 'r1', sourcePort: 0, target: 'r2', targetPort: 0 },
  { id: 're2',  source: 'r2', sourcePort: 0, target: 'r3', targetPort: 0 },
  { id: 're3',  source: 'r3', sourcePort: 0, target: 'r4', targetPort: 0 },
  { id: 're4',  source: 'r4', sourcePort: 0, target: 'r5', targetPort: 0 }, // X_train → lin_reg
  { id: 're5',  source: 'r4', sourcePort: 1, target: 'r5', targetPort: 1 }, // y_train → lin_reg
  { id: 're6',  source: 'r5', sourcePort: 0, target: 'r6', targetPort: 0 }, // model → metrics
  { id: 're7',  source: 'r4', sourcePort: 2, target: 'r6', targetPort: 1 }, // X_test → metrics
  { id: 're8',  source: 'r4', sourcePort: 3, target: 'r6', targetPort: 2 }, // y_test → metrics
  { id: 're9',  source: 'r5', sourcePort: 0, target: 'r7', targetPort: 0 }, // model → residual
  { id: 're10', source: 'r4', sourcePort: 2, target: 'r7', targetPort: 1 }, // X_test → residual
  { id: 're11', source: 'r4', sourcePort: 3, target: 'r7', targetPort: 2 }, // y_test → residual
]

const NLP_NODES: PipelineNode[] = [
  { id: 't1', type: 'csv_loader', position: { x: 60,   y: 100 }, status: 'idle', config: { path: 'nlp_data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 't2', type: 'tfidf',      position: { x: 320,  y: 100 }, status: 'idle', config: { col: 'text', method: 'TF-IDF', max_features: 5000 } },
  { id: 't3', type: 'train_test', position: { x: 580,  y: 100 }, status: 'idle', config: {} },
  { id: 't4', type: 'log_reg',    position: { x: 840,  y: 80  }, status: 'idle', config: {} },
  { id: 't5', type: 'metrics',    position: { x: 1100, y: 80  }, status: 'idle', config: {} },
  { id: 't6', type: 'shap',       position: { x: 1100, y: 220 }, status: 'idle', config: {} },
]
const NLP_EDGES: PipelineEdge[] = [
  { id: 'te1', source: 't1', sourcePort: 0, target: 't2', targetPort: 0 },
  { id: 'te2', source: 't2', sourcePort: 0, target: 't3', targetPort: 0 },
  { id: 'te3', source: 't3', sourcePort: 0, target: 't4', targetPort: 0 }, // X_train → log_reg
  { id: 'te4', source: 't3', sourcePort: 1, target: 't4', targetPort: 1 }, // y_train → log_reg
  { id: 'te5', source: 't4', sourcePort: 0, target: 't5', targetPort: 0 }, // model → metrics
  { id: 'te6', source: 't3', sourcePort: 2, target: 't5', targetPort: 1 }, // X_test → metrics
  { id: 'te7', source: 't3', sourcePort: 3, target: 't5', targetPort: 2 }, // y_test → metrics
  { id: 'te8', source: 't4', sourcePort: 0, target: 't6', targetPort: 0 }, // model → shap
  { id: 'te9', source: 't3', sourcePort: 2, target: 't6', targetPort: 1 }, // X_test → shap
]

const AUTOML_NODES: PipelineNode[] = [
  { id: 'a1', type: 'csv_loader',  position: { x: 60,   y: 100 }, status: 'idle', config: { path: 'data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 'a2', type: 'imputer',     position: { x: 320,  y: 100 }, status: 'idle', config: { strategy: 'mean', fill_value: '0', cols: '' } },
  { id: 'a3', type: 'train_test',  position: { x: 580,  y: 100 }, status: 'idle', config: { test_size: 0.2, random_state: 42, stratify: false } },
  { id: 'a4', type: 'automl',      position: { x: 840,  y: 80  }, status: 'idle', config: { task: 'auto', metric: 'auto', time_budget: 30, n_trials: 0, estimators: '', eval_method: 'auto', random_state: 42 } },
  { id: 'a5', type: 'metrics',     position: { x: 1100, y: 60  }, status: 'idle', config: { task: 'classification', average: 'weighted' } },
  { id: 'a6', type: 'conf_matrix', position: { x: 1100, y: 220 }, status: 'idle', config: { normalize: 'none', cmap: 'Blues' } },
]
const AUTOML_EDGES: PipelineEdge[] = [
  { id: 'ae1', source: 'a1', sourcePort: 0, target: 'a2', targetPort: 0 },
  { id: 'ae2', source: 'a2', sourcePort: 0, target: 'a3', targetPort: 0 },
  { id: 'ae3', source: 'a3', sourcePort: 0, target: 'a4', targetPort: 0 }, // X_train -> automl
  { id: 'ae4', source: 'a3', sourcePort: 1, target: 'a4', targetPort: 1 }, // y_train -> automl
  { id: 'ae5', source: 'a4', sourcePort: 0, target: 'a5', targetPort: 0 }, // best model -> metrics
  { id: 'ae6', source: 'a3', sourcePort: 2, target: 'a5', targetPort: 1 },
  { id: 'ae7', source: 'a3', sourcePort: 3, target: 'a5', targetPort: 2 },
  { id: 'ae8', source: 'a4', sourcePort: 0, target: 'a6', targetPort: 0 }, // best model -> confusion matrix
  { id: 'ae9', source: 'a3', sourcePort: 2, target: 'a6', targetPort: 1 },
  { id: 'ae10', source: 'a3', sourcePort: 3, target: 'a6', targetPort: 2 },
]

const FORECAST_NODES: PipelineNode[] = [
  { id: 'f1', type: 'csv_loader', position: { x: 60,  y: 140 }, status: 'idle', config: { path: 'timeseries_data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 'f2', type: 'ts_split',   position: { x: 340, y: 60  }, status: 'idle', config: { date_col: 'date', test_periods: 28, test_fraction: 0.2 } },
  { id: 'f3', type: 'forecaster', position: { x: 640, y: 0   }, status: 'idle', config: { target: 'sales', method: 'ets' } },
  { id: 'f4', type: 'forecaster', position: { x: 640, y: 200 }, status: 'idle', config: { target: 'sales', method: 'seasonal_naive' } },
  { id: 'f5', type: 'backtest',   position: { x: 340, y: 300 }, status: 'idle', config: { target: 'sales', method: 'ets', folds: 4, horizon: 28 } },
]
const FORECAST_EDGES: PipelineEdge[] = [
  { id: 'fe1', source: 'f1', sourcePort: 0, target: 'f2', targetPort: 0 },
  { id: 'fe2', source: 'f2', sourcePort: 0, target: 'f3', targetPort: 0 }, // train -> ETS
  { id: 'fe3', source: 'f2', sourcePort: 1, target: 'f3', targetPort: 1 }, // test -> ETS
  { id: 'fe4', source: 'f2', sourcePort: 0, target: 'f4', targetPort: 0 }, // train -> seasonal naive (the baseline)
  { id: 'fe5', source: 'f2', sourcePort: 1, target: 'f4', targetPort: 1 },
  { id: 'fe6', source: 'f1', sourcePort: 0, target: 'f5', targetPort: 0 }, // full series -> backtest
]

const CLUSTER_NODES: PipelineNode[] = [
  { id: 'k1', type: 'csv_loader',   position: { x: 60,  y: 100 }, status: 'idle', config: { path: 'customers_data.csv', sep: ',', header: true, encoding: 'utf-8' } },
  { id: 'k2', type: 'kmeans',       position: { x: 340, y: 100 }, status: 'idle', config: { n_clusters: 0, k_max: 8 } },
  { id: 'k3', type: 'cluster_eval', position: { x: 620, y: 100 }, status: 'idle', config: {} },
]
const CLUSTER_EDGES: PipelineEdge[] = [
  { id: 'ke1', source: 'k1', sourcePort: 0, target: 'k2', targetPort: 0 },
  { id: 'ke2', source: 'k2', sourcePort: 0, target: 'k3', targetPort: 0 }, // labelled rows -> evaluation
]

export const TEMPLATES = {
  classification: { nodes: STARTER_NODES, edges: STARTER_EDGES },
  regression: { nodes: REGRESSION_NODES, edges: REGRESSION_EDGES },
  nlp: { nodes: NLP_NODES, edges: NLP_EDGES },
  automl: { nodes: AUTOML_NODES, edges: AUTOML_EDGES },
  forecasting: { nodes: FORECAST_NODES, edges: FORECAST_EDGES },
  clustering: { nodes: CLUSTER_NODES, edges: CLUSTER_EDGES },
}

let nodeCounter = 100

/** A new node id, never reused in this session (node ids are stable and never reused after deletion). */
export function nextNodeId(): string { return `n_${++nodeCounter}` }

/** Every node id in a pipeline, including the ones inside subflows (they come back when a subflow is ungrouped). */
function allIds(nodes: Array<{ id: string; type: string; config: Record<string, unknown> }>): string[] {
  return nodes.flatMap(n => [n.id, ...(n.type === 'subflow' ? allIds(((n.config.nodes ?? []) as typeof nodes)) : [])])
}

interface PipelineState {
  nodes: PipelineNode[]
  edges: PipelineEdge[]
  selectedNodeId: string | null
  selectedEdgeId: string | null
  history: HistoryEntry[]
  historyIndex: number
  isDirty: boolean
  fitViewGeneration: number

  addNode: (type: string, position: { x: number; y: number }, config?: Record<string, unknown>) => void
  removeNode: (id: string) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  updateNodePolicy: (id: string, policy: NodePolicy) => void
  moveNode: (id: string, position: { x: number; y: number }) => void
  /** Group nodes into one subflow node (one undo step). Returns an error message, or null. */
  groupNodes: (ids: string[], name?: string) => string | null
  /** Put a subflow's nodes back on the canvas (one undo step). */
  ungroupNode: (id: string) => void
  /** Move many nodes at once (Tidy layout) as one undo step. */
  applyLayout: (positions: Record<string, { x: number; y: number }>) => void
  addEdge: (edge: PipelineEdge) => void
  removeEdge: (id: string) => void
  setSelectedNode: (id: string | null) => void
  setSelectedEdge: (id: string | null) => void
  /** Pipeline name, description and metadata (e.g. tracking settings). */
  meta: PipelineMeta
  setMeta: (patch: Partial<PipelineMeta>) => void
  loadPipeline: (nodes: PipelineNode[], edges: PipelineEdge[], meta?: PipelineMeta) => void
  clear: () => void
  undo: () => void
  redo: () => void
  setNodeStatus: (id: string, status: NodeStatus) => void
  resetAllNodeStatuses: () => void
  toPipelineSpec: () => PipelineSpec
}

function pushHistory(state: { history: HistoryEntry[]; historyIndex: number }, nodes: PipelineNode[], edges: PipelineEdge[]) {
  const next = [...state.history.slice(0, state.historyIndex + 1), { nodes, edges }].slice(-50)
  return { history: next, historyIndex: next.length - 1 }
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  selectedEdgeId: null,
  history: [{ nodes: [], edges: [] }],
  historyIndex: 0,
  isDirty: false,
  fitViewGeneration: 0,

  addNode: (type, position, config) => {
    const spec = NODE_REGISTRY[type]
    if (!spec && !(type === 'subflow' && config)) return  // subflows carry their own config (from the library)
    const defaultConfig: Record<string, unknown> = {}
    spec?.config.forEach(f => { defaultConfig[f.id] = f.default })
    const newNode: PipelineNode = { id: nextNodeId(), type, position, config: config ?? defaultConfig, status: 'idle' }
    set(s => {
      const nodes = [...s.nodes, newNode]
      return { nodes, isDirty: true, ...pushHistory(s, nodes, s.edges) }
    })
  },

  removeNode: (id) => {
    set(s => {
      const nodes = s.nodes.filter(n => n.id !== id)
      const edges = s.edges.filter(e => e.source !== id && e.target !== id)
      return { nodes, edges, selectedNodeId: null, isDirty: true, ...pushHistory(s, nodes, edges) }
    })
  },

  updateNodePolicy: (id, policy) => {
    set(s => ({ nodes: s.nodes.map(n => n.id === id ? { ...n, policy: pickPolicy(policy) } : n), isDirty: true }))
  },

  updateNodeConfig: (id, config) => {
    set(s => ({ nodes: s.nodes.map(n => n.id === id ? { ...n, config } : n), isDirty: true }))
  },

  moveNode: (id, position) => {
    set(s => ({ nodes: s.nodes.map(n => n.id === id ? { ...n, position } : n), isDirty: true }))
  },

  groupNodes: (ids, name = 'Subflow') => {
    const s = get()
    const res = groupSubflow(s.nodes, s.edges, ids, nextNodeId(), name)
    if ('error' in res) return res.error
    set(st => ({ nodes: res.nodes, edges: res.edges, selectedNodeId: res.id, selectedEdgeId: null, isDirty: true, ...pushHistory(st, res.nodes, res.edges) }))
    return null
  },

  ungroupNode: (id) => {
    set(s => {
      const res = ungroupSubflow(s.nodes, s.edges, id)
      return { nodes: res.nodes, edges: res.edges, selectedNodeId: null, isDirty: true, ...pushHistory(s, res.nodes, res.edges) }
    })
  },

  applyLayout: (positions) => {
    set(s => {
      const nodes = s.nodes.map(n => positions[n.id] ? { ...n, position: positions[n.id] } : n)
      // Drags aren't history entries, so record the current positions first: undo returns exactly here.
      const before = pushHistory(s, s.nodes, s.edges)
      return { nodes, isDirty: true, fitViewGeneration: s.fitViewGeneration + 1, ...pushHistory(before, nodes, s.edges) }
    })
  },

  addEdge: (edge) => {
    set(s => {
      if (s.edges.some(e => e.source === edge.source && e.sourcePort === edge.sourcePort && e.target === edge.target && e.targetPort === edge.targetPort)) {
        return s
      }
      const edges = [...s.edges, edge]
      return { edges, isDirty: true, ...pushHistory(s, s.nodes, edges) }
    })
  },

  removeEdge: (id) => {
    set(s => {
      const edges = s.edges.filter(e => e.id !== id)
      return { edges, selectedEdgeId: null, isDirty: true, ...pushHistory(s, s.nodes, edges) }
    })
  },

  setSelectedNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  setSelectedEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),

  meta: DEFAULT_META,
  setMeta: (patch) => set(s => ({ meta: { ...s.meta, ...patch }, isDirty: true })),

  loadPipeline: (nodes, edges, meta) => {
    // Advance nodeCounter past any loaded node IDs so new drops never collide.
    for (const id of allIds(nodes)) {
      const m = id.match(/^n_(\d+)$/)
      if (m) nodeCounter = Math.max(nodeCounter, parseInt(m[1], 10))
    }
    set(s => ({ nodes, edges, meta: meta ?? DEFAULT_META, selectedNodeId: null, selectedEdgeId: null, isDirty: false, fitViewGeneration: s.fitViewGeneration + 1, ...pushHistory(s, nodes, edges) }))
  },

  clear: () => {
    set(s => {
      const nodes: PipelineNode[] = []
      const edges: PipelineEdge[] = []
      return { nodes, edges, selectedNodeId: null, selectedEdgeId: null, isDirty: true, ...pushHistory(s, nodes, edges) }
    })
  },

  undo: () => {
    set(s => {
      if (s.historyIndex <= 0) return s
      const idx = s.historyIndex - 1
      const h = s.history[idx]
      return { nodes: h.nodes, edges: h.edges, historyIndex: idx }
    })
  },

  redo: () => {
    set(s => {
      if (s.historyIndex >= s.history.length - 1) return s
      const idx = s.historyIndex + 1
      const h = s.history[idx]
      return { nodes: h.nodes, edges: h.edges, historyIndex: idx }
    })
  },

  setNodeStatus: (id, status) => {
    set(s => ({ nodes: s.nodes.map(n => n.id === id ? { ...n, status } : n) }))
  },

  resetAllNodeStatuses: () => {
    set(s => ({ nodes: s.nodes.map(n => ({ ...n, status: 'idle' as NodeStatus })) }))
  },

  toPipelineSpec: () => {
    const { nodes, edges, meta } = get()
    return {
      version: 2,
      name: meta.name || 'untitled',
      description: meta.description,
      metadata: meta.metadata,
      nodes: nodes.map(n => ({ id: n.id, type: n.type, position: n.position, config: n.config, ...pickPolicy(n.policy ?? {}) })),
      edges: edges.map(e => ({ id: e.id, source: e.source, target: e.target, source_port: e.sourcePort, target_port: e.targetPort })),
    }
  },
}))
