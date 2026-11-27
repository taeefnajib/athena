# Frontend — `frontend/CLAUDE.md`

> Read the root `CLAUDE.md` first. This file covers the React client only.

## 1. Mandate

Build the visual layer of Athena: a fullscreen, infinite-canvas pipeline editor with a node library, inspector panel, and live execution feedback. The frontend is a **dumb client** — all ML logic lives in the backend. The frontend's jobs are:

1. Let users build a valid `PipelineSpec` (root §4.1) by direct manipulation.
2. Send it to the backend and render the WS event stream as live node states.
3. Save / load `.athena` files via the backend.
4. Render artifact previews returned by the backend.

That's it. The frontend never executes ML code, never owns "ground truth" about a pipeline's results, and never silently transforms data.

---

## 2. Stack

- **React 18** + **TypeScript** (strict mode, no `any`)
- **Vite** for dev/build
- **`@xyflow/react`** v12 for the graph canvas
- **Zustand** for state (no Redux, no Context-as-store)
- **Tailwind CSS** + CSS variables for theme tokens
- **Framer Motion** for sidebar slides, modals, toast fades
- **lucide-react** for icons (consistent stroke style; don't mix icon libraries)
- **clsx** for conditional classes
- **Vitest** + **React Testing Library** for tests

Do not add: Material UI, Chakra, Ant Design, styled-components, Emotion, Redux Toolkit. Tailwind + headless components is the way.

---

## 3. Directory layout

```
frontend/src/
├── main.tsx                  # Vite entry
├── App.tsx                   # Top-level layout (TopBar / LeftSidebar / Canvas / RightSidebar)
├── components/
│   ├── TopBar/               # logo, run/stop/save/export buttons, status pill, theme toggle
│   ├── LeftSidebar/          # node library — search + categorized draggables
│   ├── RightSidebar/         # inspector — Settings / Data / Logs / Metrics tabs
│   ├── GraphCanvas/          # ReactFlow wrapper, minimap, controls, drop handler
│   ├── modals/               # ExportModal, TemplatesModal, SettingsModal
│   └── ui/                   # Button, Toast, Tabs, Tooltip — primitives, no business logic
├── nodes/
│   ├── BaseNode.tsx          # the generic custom node — used by ~all types
│   ├── CustomCodeNode.tsx    # exception: needs a code-mirror textarea
│   └── index.ts              # nodeTypes map for ReactFlow
├── store/
│   ├── pipelineStore.ts      # nodes, edges, selectedId, undo/redo history
│   ├── executionStore.ts     # runId, perNodeStatus, logs, previews, metrics
│   └── uiStore.ts            # theme, openModals, sidebarVisibility
├── lib/
│   ├── api.ts                # fetch client for /api routes
│   ├── ws.ts                 # WebSocket client for /ws/runs/:id
│   ├── dag.ts                # topo sort, cycle detection (mirrors backend; for client-side validation)
│   ├── validation.ts         # connection-type validation
│   └── serialize.ts          # PipelineSpec <-> ReactFlow nodes/edges
├── registry/
│   └── nodeRegistry.ts       # SINGLE SOURCE OF TRUTH for node UI metadata
├── hooks/
│   ├── useTheme.ts
│   ├── useKeyboardShortcuts.ts
│   ├── useAutosave.ts
│   └── useRunPipeline.ts     # orchestrates POST /run + WS subscription
├── types/
│   └── pipeline.ts           # mirrors backend Pydantic schemas
└── styles/
    └── globals.css           # CSS vars (light/dark) + tailwind directives
```

---

## 4. State management with Zustand

Three stores. Keep them independent — do not let one import another's hooks.

### `pipelineStore`
The pipeline structure. Operations: `addNode`, `removeNode`, `updateNodeConfig`, `moveNode`, `addEdge`, `removeEdge`, `loadPipeline`, `clear`, `undo`, `redo`.

History is a bounded ring buffer (50 entries) of `{ nodes, edges }` snapshots. Push on every structural change; **don't push on per-keystroke config edits** — debounce config changes by 400ms before snapshotting, otherwise typing in a textarea floods history.

### `executionStore`
Per-run state. Cleared at the start of every run. Shape:
```ts
{
  runId: string | null
  status: 'idle' | 'running' | 'completed' | 'error'
  currentNodeId: string | null            // for highlighting
  nodeStates: Record<NodeId, NodeRunState>
  logs: Record<NodeId, LogEntry[]>
  previews: Record<NodeId, ArtifactPreview>
  metrics: Record<NodeId, Record<string, number>>
}
```

### `uiStore`
`theme: 'light' | 'dark' | 'system'`, modal visibility booleans, selected tab in inspector. Persists to `localStorage` via Zustand's `persist` middleware.

**Do not put React Flow's internal state in Zustand.** Use React Flow's own hooks (`useNodes`, `useEdges`) for the canvas, and sync to `pipelineStore` only on commit (drag end, edge connect). Mirroring everything causes thrash.

---

## 5. The node registry

Node specs come from the backend node SDK. `registry/nodeRegistry.ts` holds only the types (`NodeSpec`, `ConfigField`, …), the loaded `NODE_REGISTRY` / `CATEGORY_META`, and presentation helpers. `main.tsx` calls `loadNodeRegistry()` (`GET /api/nodes`) before the app renders and shows a "Couldn't reach the Athena backend" screen with Retry if it fails.

- **Never hand-add node entries in the frontend.** Add or change a node with `@node` in the backend; the library and inspector forms follow automatically.
- `PortType` and `NodeCategory` are open strings, because plugins can add new ones. Built-in categories use the `--cat-<id>` CSS variables; others get a stable colour from `categoryColor()`.
- `getNodeGroups()` leaves out nodes with `available: false` (not implemented yet). They stay in `NODE_REGISTRY` so older pipelines that use them still load.
- Each spec carries `exportable` / `export_note`, so the UI can say which nodes export to code.
- Unit tests that need specs call `applyNodesResponse()` with a small fixture (see `registry/nodeRegistry.test.ts`).

Connection validity is checked in `lib/validation.ts` against the loaded specs.

---

## 6. Components — UX rules per area

### TopBar
Layout (left → right): logo · Run · Stop · | · Undo · Redo · | · Save · Templates · Export · {flex} · stats · status pill · theme toggle.
- Run is disabled while `status === 'running'`.
- Stop is disabled while `status !== 'running'`.
- Status pill uses an animated pulsing dot when running.
- Status colors come from CSS vars (`--success`, `--error`, `--running`, `--text-muted`).

### LeftSidebar (Node Library)
- Search input at the top, debounced 150ms, matches against `label` and `description`.
- Categories collapsible, all expanded by default. Persist collapsed state per session (sessionStorage, not localStorage).
- Each row is `draggable={true}`. On `dragstart`, set `dataTransfer.setData('application/athena-node', nodeType)`.
- Color-code the leftmost 3px of each row by `category` (CSS var).
- Show node icon + label + a tiny truncated description on hover.

### GraphCanvas
- Use React Flow's `<Background variant="dots">` with `gap={20} size={1.5}`.
- `<Controls>` and `<MiniMap>` enabled. MiniMap colored by node category.
- `snapToGrid={true}`, `snapGrid={[20, 20]}`.
- Drop handler reads `application/athena-node`, projects screen coords to flow coords, calls `pipelineStore.addNode`.
- Custom edge: bezier with a soft glow when selected. Animate dashes only on edges whose source node is currently `running` (use Framer Motion or a CSS keyframe).
- Click empty canvas → deselect. Click node → set `selectedId`. Click edge → set `selectedEdgeId`. Selecting either opens the right sidebar in the appropriate mode (node inspector vs edge details).
- `onConnect` calls `validation.isValidConnection(source, target, sourcePort, targetPort)` and rejects with a toast if mismatched.

### RightSidebar (Inspector)
Width: 320px on desktop, slides in from the right when something is selected, slides out when nothing is. Use Framer Motion `AnimatePresence` for mount/unmount.

Tabs: **Settings** (default), **Data Preview**, **Logs**, **Metrics**.

- **Settings**: render a form derived from `node.config` schema. Each `ConfigField.type` maps to a component in `components/ui/`. Update the store on `onChange` for toggles/selects, on `onBlur` for text/textarea (avoid spamming history during typing). Validation: numbers must be numbers; required fields highlighted on save.
- **Data Preview**: read from `executionStore.previews[nodeId]`. If absent (node hasn't run), show "Run the pipeline to see a preview." If present and `kind === 'dataframe'`, render a virtualized table (use `@tanstack/react-table` for sort, but virtualization can be naive for ≤50 rows). If `kind === 'plot'`, render the base64 PNG centered with a download button.
- **Logs**: read from `executionStore.logs[nodeId]`. Monospace, color-coded by level. Auto-scroll to bottom while running, freeze when user scrolls up.
- **Metrics**: read from `executionStore.metrics[nodeId]`. Show as a small grid of stat cards. Format numbers to 4 decimal places.

### Modals
- Templates modal lists the 3 starter templates (Classification, Regression, NLP). Loading a template clears the current pipeline and pushes a single history entry.
- Export modal: 4 buttons (Python, Notebook, JSON, .pkl). Each calls `POST /api/pipelines/export` with the format and triggers a browser download from the response.
- Settings modal: theme override (system/light/dark), cache controls (clear cache button), telemetry toggle (always off, just shown for transparency).

---

## 7. Theming

CSS variables in `styles/globals.css`. Two themes — `:root[data-theme="light"]` and `:root[data-theme="dark"]`. Toggle by setting the attribute on `<html>`. Use Tailwind's `theme.extend.colors` to map var names to Tailwind utilities (e.g., `bg-panel`, `text-muted`).

Required vars (match the prototype):
```
--bg, --panel, --card, --card2, --border, --border2,
--text, --text-dim, --text-muted,
--accent, --accent-glow, --accent2,
--success, --warning, --error, --running,
--shadow, --shadow-lg, --radius, --radius-lg,
--cat-data, --cat-quality, --cat-feature, --cat-balance, --cat-split,
--cat-model, --cat-advanced, --cat-ensemble, --cat-eval, --cat-interp,
--cat-deploy, --cat-monitor, --cat-cluster, --cat-forecast
```

Don't hardcode hex colors anywhere in components. If you need a color that isn't a var, add the var first.

---

## 8. Pipeline run flow (the most important client logic)

`hooks/useRunPipeline.ts`:

```ts
async function run(spec: PipelineSpec, opts?: { startFrom?: string[] }) {
  // 1. Client-side validation: cycle check, port-type check on every edge.
  //    Fail fast with a toast if invalid; don't bother the backend.
  const errors = validate(spec)
  if (errors.length) { toast.error(errors[0]); return }

  // 2. POST /api/pipelines/run -> { run_id }
  executionStore.reset()
  executionStore.setStatus('running')
  const { run_id } = await api.runPipeline(spec, opts)
  executionStore.setRunId(run_id)

  // 3. Open WS, dispatch events to executionStore.
  const ws = openRunWS(run_id, {
    onNodeStart:  e => executionStore.markRunning(e.node_id),
    onNodeLog:    e => executionStore.appendLog(e.node_id, e),
    onNodeFinish: e => executionStore.markFinished(e.node_id, e),
    onRunFinish:  e => executionStore.setStatus(e.status),
    onError:      e => executionStore.setStatus('error'),
  })
  return () => ws.close()
}
```

Key invariants:
- Only one run in flight at a time. The Run button is disabled while `status === 'running'`.
- Stop = `POST /api/runs/{id}/cancel` + close WS. Don't try to reach into the WS to interrupt mid-message.
- The frontend is **strictly a consumer** of run state. It never decides a node "succeeded" — it waits for the backend to say so.

---

## 9. Save / Load / Autosave

- Save: `POST /api/pipelines/save { path, spec }`. Path is a local FS path the user types or picks via a native file dialog (browsers can't open native dialogs from JS — fall back to text input + a "Choose..." button that uses the File System Access API where available).
- Load: `POST /api/pipelines/load { path } -> { spec }`. Pipe through `serialize.fromPipelineSpec` to repopulate the store.
- Autosave: `useAutosave` hook subscribes to `pipelineStore` and POSTs to `/api/pipelines/autosave` every 10s when dirty. On app mount, GET `/api/pipelines/autosave/latest` and prompt the user to recover if it differs from the last saved file.

---

## 10. Error handling & toasts

- Network error → toast "Couldn't reach the backend. Is `uvicorn` running on :8000?" with a Retry action.
- Validation error (cycle, missing config) → toast with the specific issue and node id.
- Backend `node_finish` with `status: error` → don't toast (the inspector already shows it). Only toast on `run_finish: error` with a one-liner like "Pipeline failed at node {id}: {message}".

Use a single `<Toaster />` mounted at app root. Three toast types: `info`, `success`, `error`. Auto-dismiss after 3.5s; errors stay until clicked.

---

## 11. Performance

- Memoize `BaseNode` with `React.memo` and a comparator that ignores position (React Flow handles position re-renders internally).
- Don't re-render the inspector on every WS log message — batch logs in `executionStore` with a 100ms flush.
- Virtualize the node library only if it grows beyond ~80 nodes. With the current ~50, plain rendering is fine.

---

## 12. Testing

- Unit-test `lib/dag.ts`, `lib/validation.ts`, `lib/serialize.ts`. These are pure and break the most when changed.
- Component-test the inspector form rendering for each `ConfigField.type`.
- Integration-test "drag CSV Loader → connect to Imputer → click Run → see green nodes" with a mocked WS that emits the expected event sequence.
- Skip snapshot tests for whole pages — they're noisy and reviewers ignore them.

---

## 13. What not to do

- Don't run any ML logic in the browser. Even a "preview" — ask the backend.
- Don't store the entire dataset in Zustand. Previews only.
- Don't fight React Flow. If something is awkward, the answer is almost always "use the React Flow primitive correctly" not "wrap it in a custom abstraction".
- Don't add real-time collaboration. Single-user.
- Don't add user accounts, login pages, or "share" buttons.
- Don't put inline styles for anything that could be a Tailwind class. The prototype's inline styles are convenient for a single-file demo; in the real app, use Tailwind.
- Don't depend on undocumented backend behavior. If a contract is unclear, ask — or document it in the root `CLAUDE.md` §4 in the same change.
