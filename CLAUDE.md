# Athena — Open-Source Visual ML Engineering Platform

> A graph-based machine learning workflow platform. Users design ML pipelines visually (Figma-meets-Notion-meets-data-science-IDE), and Athena executes them with real Python ML libraries underneath. It is growing from a local AutoML prototype into an open alternative to SageMaker Canvas that covers the full lifecycle. **`docs/ROADMAP.md` is the plan of record: read it before starting feature work.**

This is the **root `CLAUDE.md`**. It defines the product, the architecture, and the contract between frontend and backend. Two sub-`CLAUDE.md` files contain the implementation rules for each side:

- `frontend/CLAUDE.md` — React + TypeScript + React Flow client
- `backend/CLAUDE.md` — FastAPI + scikit-learn / XGBoost / pandas runtime

Always read this file first, then the sub-file relevant to the area you're editing. If a change spans both sides (e.g., adding a new node type), update **both**.

---

## 1. Product vision

Athena is a **local desktop-class web application** that lets users build, run, evaluate, and export end-to-end ML pipelines without writing code — while keeping everything transparent and exportable to clean Python.

The user opens `http://localhost:5173` in a browser. The UI feels like a design tool. They drag a "CSV Loader" node onto the canvas, connect it to "Imputer" → "Train/Test Split" → "Random Forest" → "Metrics", click **Run**, and watch nodes light up green as the backend executes them in topological order. They can inspect intermediate dataframes, see metrics, and export the entire pipeline as a self-contained Python script or Jupyter notebook.

Core principles:

1. **Local-first.** `pip install athena && athena` works on a laptop with no infrastructure, no account and no telemetry. Athena may connect *out* to services the user configures (MLflow, databases, warehouses, Kubernetes, model APIs) using the user's own credentials, but it never requires one. A multi-user server mode is a later roadmap phase that is additive: never break the single-user local path.
2. **Transparent.** Every visual node maps to a real, readable Python function. The exported script must be code a data scientist would actually write. Visual-first, not visual-only: config, generated code, runtime and logs are always inspectable.
3. **Honest about state.** A node is `idle`, `running`, `success`, or `error` — these reflect **actual backend execution**, not animations. No fake spinners.
4. **DAG-correct.** Pipelines are directed acyclic graphs. Cycles are rejected before execution. Topological order is computed once per run.
5. **Resumable & cacheable.** Re-running a pipeline reuses cached outputs of unchanged upstream nodes. Editing a node invalidates its descendants only.

---

## 2. Repository layout

```
athena/
├── CLAUDE.md                 # this file — read first
├── README.md                 # user-facing setup guide
├── pyproject.toml            # backend deps + tooling (ruff, mypy, pytest)
├── package.json              # workspace root, scripts to run both sides
├── .gitignore
│
├── frontend/
│   ├── CLAUDE.md             # frontend-specific rules
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/       # TopBar, LeftSidebar, RightSidebar, GraphCanvas, modals
│       ├── nodes/            # one file per node type's React Flow custom node
│       ├── store/            # Zustand stores (pipeline, execution, ui)
│       ├── lib/              # api client, validation, code-gen helpers, dag utils
│       ├── registry/         # nodeRegistry.ts — single source of truth for node specs
│       ├── hooks/
│       ├── styles/           # globals.css with CSS variables for theming
│       └── types/            # shared TS types matching backend Pydantic models
│
└── backend/
    ├── CLAUDE.md             # backend-specific rules
    ├── athena/               # python package
    │   ├── __init__.py
    │   ├── main.py           # FastAPI app entrypoint
    │   ├── api/              # routers: pipeline, nodes, artifacts, ws
    │   ├── core/
    │   │   ├── executor.py   # DAG executor with caching
    │   │   ├── registry.py   # NODE_REGISTRY dict mapping type -> handler
    │   │   ├── context.py    # ExecutionContext object passed between handlers
    │   │   ├── cache.py      # content-addressed artifact cache
    │   │   └── codegen.py    # pipeline.json -> python script / notebook
    │   ├── nodes/            # one file per category (data.py, model.py, eval.py, …)
    │   ├── schemas/          # Pydantic models — must mirror frontend types
    │   ├── storage/          # save/load .athena pipeline files
    │   └── utils/
    └── tests/
```

The two sides are independent processes:
- Backend: `uvicorn athena.main:app --reload --port 8000`
- Frontend: `vite` on `5173`, proxies `/api` and `/ws` to `8000`

A top-level `npm run dev` launches both concurrently. Document this in README.

---

## 3. Architecture at a glance

```
 ┌────────────── Browser (React + React Flow) ──────────────┐
 │  Pipeline state (Zustand) ──> serialize to PipelineSpec  │
 │  POST /api/pipelines/run  ──────────────────────────────┐ │
 │  WS /ws/runs/{run_id}  <── per-node status events       │ │
 └──────────────────────────────────────────────────────────┘ │
                                                              ▼
 ┌──────────── FastAPI backend ────────────────────────────────┐
 │  Validate spec (Pydantic) → topo sort → cycle check         │
 │  Executor walks DAG:                                        │
 │    for each node in topo order:                             │
 │      ctx.inputs = artifacts from upstream edges             │
 │      handler = NODE_REGISTRY[node.type].handler             │
 │      ctx.outputs = handler(node.config, ctx.inputs)         │
 │      cache(ctx.outputs, key=hash(node + upstream))          │
 │      emit ws event {node_id, status, preview, logs}         │
 │  On any handler error → mark node error, halt downstream    │
 └─────────────────────────────────────────────────────────────┘
```

**The artifact graph is in-memory per run.** Datasets are pandas DataFrames, models are fitted estimators, plots are base64 PNGs or JSON for client-side rendering. Large artifacts are spilled to a per-run temp dir on disk and referenced by ID.

---

## 4. Frontend ↔ backend contract (read carefully — both sides depend on it)

### 4.1 PipelineSpec (the on-the-wire format)

This is what the frontend sends to `POST /api/pipelines/run` and what's saved as `.athena` files:

```jsonc
{
  "version": 1,
  "nodes": [
    {
      "id": "n1",                   // stable id assigned client-side
      "type": "csv_loader",         // must be a registered node type (GET /api/nodes)
      "position": { "x": 60, "y": 80 },  // for canvas only — backend ignores
      "config": {                   // shape determined by node type
        "path": "data.csv",
        "sep": ",",
        "header": true,
        "encoding": "utf-8"
      },
      // v2, all optional: execution policy
      "timeout_s": 120,             // overrides ATHENA_NODE_TIMEOUT_S
      "retry": { "max_attempts": 3, "backoff_s": 2 },
      "cache": true,                // false = always re-run (live data)
      "runtime": null,              // only "python" (local worker) today
      "resources": { "cpu": 2, "memory_gb": 4, "gpu": 0 }   // advisory locally
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": "n1",
      "target": "n2",
      "source_port": 0,             // index into outputs[] of source node
      "target_port": 0              // index into inputs[] of target node
    }
  ]
}
```

Pipeline-level `metadata.tracking` (`{ enabled, connection, experiment, log_models, log_code }`) turns on MLflow tracking for every run; `connection: ""` is Athena's local store.

`version` is 2 (spec v2). The backend accepts v1 files (a strict subset) and upgrades them; the frontend keeps the v2 node fields through load and save (`pickPolicy` in `types/pipeline.ts`). Nodes reference external systems only by **connection name** (`"connection": "warehouse"`); credentials never appear in a spec.

The backend must accept this verbatim. The frontend must produce nothing else. Schema drift between sides is the #1 thing to avoid — every change to a node's `config` shape is a breaking change to both halves.

### 4.2 Node definitions have **one** source: the backend node SDK

A node is defined once, in Python, with `@node(...)` from `athena.sdk` (see `backend/CLAUDE.md` §4): type, label, category, description, ordered typed `inputs`/`outputs`, a Pydantic `Config` (defaults, `Literal` options and `Field(title=...)` labels drive the form), UI hints for special widgets, the handler, and an export template (or `exportable=False` with a reason).

`GET /api/nodes` serves the full spec. The frontend loads it at startup into `frontend/src/registry/nodeRegistry.ts`, which is a **loader and type definitions only** — never hand-add node entries there. Presentation-only metadata (category colours and icons) stays in the frontend, with a fallback for categories that plugins introduce.

When adding a new node type:
1. Define it with `@node` in `backend/athena/nodes/<category>.py`, or in a plugin package (entry point `athena.nodes`).
2. Supply its export code template, or set `exportable=False` with a reason.
3. Add a handler test with a fixture dataframe, and a minimal pipeline test.
4. Add a frontend custom-node component only if it needs special rendering (most nodes reuse `BaseNode`).

`tests/test_node_specs.py` fails if any node's config, ports, UI hints or export declaration are inconsistent.

### 4.3 Run lifecycle

1. Client calls `POST /api/pipelines/run` with the `PipelineSpec`. Server validates, returns `{ "run_id": "..." }` immediately.
2. Client opens `WS /ws/runs/{run_id}`.
3. Server emits messages in this order, one per node, in topological order:
   - `{ "type": "node_start",   "node_id": "n1" }`
   - `{ "type": "node_log",     "node_id": "n1", "level": "info", "msg": "..." }` (zero or more)
   - `{ "type": "node_finish",  "node_id": "n1", "status": "success", "preview": {...}, "metrics": {...}, "duration_ms": 1234 }`
     - or `{ "type": "node_finish", "node_id": "n1", "status": "error", "error": { "message": "...", "traceback": "..." } }`
4. After the last node: `{ "type": "run_finish", "status": "completed" | "error" }`.
   - At any point, observers may send `{ "type": "run_info", "tracking": {...} | null, "message": "..." | null, "warning": "..." | null }`. When the pipeline is tracked, the first one carries the MLflow run (`run_id`, `experiment`, `experiment_id`, `destination`, `url`). Warnings mean tracking had a problem; they never fail the run.
5. Client may call `POST /api/runs/{run_id}/cancel` at any point. Server stops scheduling new nodes; the in-flight node is allowed to finish or is interrupted at the next checkpoint.

### 4.4 Artifact previews

When a node finishes, the server includes a small JSON preview in the `node_finish` event so the inspector can render it without a separate fetch. Schema:

```jsonc
{
  "kind": "dataframe" | "metrics" | "plot" | "model" | "text",
  // dataframe:
  "columns": ["a", "b"], "rows": [[1, 2], ...], "shape": [1240, 14],
  // metrics:
  "values": { "accuracy": 0.92, "f1": 0.91 },
  // plot:
  "format": "png_base64", "data": "iVBORw0KG..." ,
  // model:
  "summary": "RandomForestClassifier(n_estimators=100, ...)",
  // text:
  "text": "..."
}
```

Cap dataframe previews at 50 rows × 50 columns server-side. The full artifact is fetchable from `GET /api/runs/{run_id}/artifacts/{node_id}/{port}` if the user wants to download it.

### 4.5 Errors

A node handler that raises is **not** a backend bug — it's a user-visible error. Catch in the executor, send a `node_finish` with `status: error`, a clean message, and the traceback (frontend shows the message; the traceback is collapsed under "details"). Halt downstream execution. The pipeline ends with `run_finish: error`.

Backend bugs (the executor itself failing) close the WS with code 1011. Frontend shows a generic "execution engine crashed" toast.

---

## 5. Execution semantics

- **Topological order** — Kahn's algorithm. If a cycle is detected, reject the run with HTTP 400 before opening the WS.
- **Caching** — each node's output is keyed by a hash of `(node.type, node.config, hash(upstream artifacts))`. On re-run, skip handlers whose key is unchanged. The cache lives in `~/.athena/cache/` and is purged on app close (configurable).
- **Partial runs** — `POST /api/pipelines/run` accepts an optional `start_from: [node_id, ...]`. The executor reuses cached upstream artifacts and only runs from the specified nodes downward. The frontend exposes this as "Run from selected node".
- **Concurrency** — single-pipeline-at-a-time for v1. Reject a second run with HTTP 409 while one is in flight. Nodes execute sequentially in topo order; parallelism within a level is a v2 concern.
- **Resource limits** — wrap each handler in a soft timeout (default 5 minutes, configurable per node). On timeout, mark error and continue cleanup.

---

## 6. Code export

The "Export Code" feature must produce code that runs standalone on the user's machine — no Athena dependency at runtime.

- **Python script** — uses `pandas`, `scikit-learn`, `xgboost`, etc. Each node maps to a labeled section with the same comments a careful data scientist would write. Order is the topological order. Variables are named after node ids (`df_n1`, `model_n5`, `X_train`, `y_train`, ...).
- **Jupyter notebook** — same content, one cell per node, with a markdown cell above each describing what it does.
- **Pipeline JSON** — the `PipelineSpec` from §4.1, pretty-printed.
- **Trained model** — joblib/pickle of the fitted estimator from a `model_saver` node.

Code generation lives in `backend/athena/core/codegen.py`. It is a pure function: `PipelineSpec → str`. Test it by snapshotting outputs.

---

## 7. Persistence

- `.athena` files are just `PipelineSpec` JSON with a magic header. Save/Load go through `POST /api/pipelines/save` and `POST /api/pipelines/load` (both take a path on the local filesystem).
- Auto-save: every 10 seconds when the pipeline is dirty, write to `~/.athena/autosave.athena`. Restore on app launch with a "Recover unsaved work?" prompt.
- No multi-user concept. No accounts.

---

## 8. Tech stack

The core stack below is fixed. Integrations from `docs/ROADMAP.md` (MLflow, DuckDB, SQLAlchemy, dlt, LightGBM, CatBoost, Optuna, FLAML, BentoML, Evidently, Feast, Ray, `keyring`, …) are allowed when they arrive as a node, connector or runtime plugin with its dependencies declared as an optional extra (`pip install athena[mlflow]`). The base install must stay lean and work offline.

| Layer | Choice | Why |
|---|---|---|
| Frontend framework | **React 18 + TypeScript + Vite** | spec requires TS; Vite for instant HMR |
| Graph engine | **`@xyflow/react`** (React Flow v12) | the spec asks for it; mature, performant, customisable |
| State | **Zustand** | spec; lightweight, plays nicely with React Flow |
| Styling | **Tailwind CSS** + CSS variables for theming | spec; CSS vars enable runtime light/dark swap |
| Animation | **Framer Motion** | spec; for sidebar slides, modal fades, status pulses |
| Backend | **FastAPI + uvicorn** | first-class WS, async, Pydantic v2 |
| ML libs | **pandas, numpy, scikit-learn, xgboost, imbalanced-learn, shap, lime, joblib** | match the spec's node list |
| Plotting | **matplotlib** (server-side, returned as base64 PNG); never seaborn-only — keep deps lean | |
| Package mgmt | **`uv`** for backend, **`pnpm`** for frontend (npm acceptable) | speed |

Do **not** introduce: Redux, MobX, plain Flask, Django, Streamlit, alternative graph libs, or random Tailwind plugins. If a real need arises, raise it as a discussion, don't just add it.

---

## 9. Coding standards (apply to both sides)

- **Types are mandatory.** TS strict mode on, mypy strict on. No `any`, no untyped Python defs in non-test code.
- **Small modules.** Aim for files under ~300 lines. Split by responsibility, not by category-folder dogma.
- **Pure functions where possible.** The executor, code generator, and DAG utilities should be pure and unit-tested.
- **Commit messages**: imperative, scoped — `feat(nodes): add SMOTE handler`, `fix(executor): halt downstream on error`.
- **Tests live next to features.** Backend uses pytest; frontend uses Vitest + React Testing Library.

### What to test
- DAG topo sort + cycle detection (backend)
- Each node handler in isolation with a fixture dataframe (backend)
- Code generator snapshot tests for each starter template (backend)
- Pipeline serialise/deserialise round-trip (both sides)
- Critical UI flows: drag-to-canvas, connect-ports, run-and-watch-status (frontend, with mocked WS)

### What not to test
- React Flow internals
- Third-party ML library outputs
- Animation timings

---

## 10. UX rules (cross-cutting — both sides enforce)

- **Connection validation.** A connection from output port `O` to input port `I` is valid iff their declared types match. Types are simple strings: `dataset`, `train`, `test`, `model`, `report`, `predictions`, `plot`, `endpoint`, `folds`. The frontend rejects invalid drags before they're committed; the backend re-validates on receipt and 400s if something snuck through.
- **Node IDs are stable.** Generated client-side, never reused after deletion. The backend treats them as opaque strings.
- **Don't surprise the user.** Auto-layout never moves nodes the user has positioned. Auto-save never overwrites a named file. Run-from-selected highlights what will run before running it.
- **Theme.** Light and dark are first-class. Both sides should look intentional in both themes — not "dark mode bolted on". Store choice in `localStorage`; default to system preference.
- **Keyboard shortcuts** (frontend): `⌘/Ctrl+Z` undo, `⌘/Ctrl+Shift+Z` redo, `⌘/Ctrl+S` save, `Delete` remove selected, `Space+drag` pan, `⌘/Ctrl+Enter` run, `Esc` deselect.

---

## 11. What this product is *not*

- Not a hosted product. There is no `athena.com`, no Athena account and no Athena cloud. Every integration runs on infrastructure and credentials the user controls.
- Not a reimplementation of mature MLOps tools. Orchestration, experiment tracking, serving, feature stores and data warehousing are integrated (MLflow, Dagster, BentoML, Feast, Snowflake, …), not rebuilt.
- Not a place where user code runs in the API server. Handlers and custom code execute in worker processes (`backend/athena/runtime/`), never in the request-serving process.
- Not multi-user yet. Team features (auth, RBAC, shared workspaces) belong to the server-mode phase and must not complicate the single-user local path before then.

Deep learning, distributed compute and cloud connectors are on the roadmap (phases 1–3); add them as plugins in roadmap order, not ad hoc.

---

## 12. Working agreement for Claude Code

When taking on a task:

1. **Read the relevant sub-`CLAUDE.md`** before changing any code. Frontend and backend each have their own conventions.
2. **If a change touches the frontend↔backend contract (§4)**, update both sides in the same PR. Node specs come from the backend; never re-introduce hand-written node entries in the frontend.
3. **Run the test suite** before declaring a task done — `npm test` (frontend) and `uv run pytest` (backend).
4. **Don't add a node** without: an `@node` definition, a handler test, and an export template or an explicit `exportable=False` reason.
5. **Follow the roadmap order.** Check `docs/ROADMAP.md`; update its status when a deliverable lands.
6. **Don't mock the backend in the frontend** beyond what's needed for unit tests. The dev server is the source of truth.
7. **Surface decisions, don't bury them.** If the spec is ambiguous, pick the simpler interpretation and note it in the PR description.

When in doubt: prefer fewer features done well over many features done shakily. Athena's appeal is that it **actually works** end-to-end — not that it has the most nodes.
