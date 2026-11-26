# Backend — `backend/CLAUDE.md`

> Read the root `CLAUDE.md` first. This file covers the Python execution engine only.

## 1. Mandate

The backend is the **brain** of Athena. It owns:

1. The canonical node registry — the actual ML logic.
2. DAG validation, topological scheduling, and execution.
3. Artifact lifecycle: produce, cache, preview, expose for download.
4. Code generation: pipeline → standalone Python script / notebook.
5. Pipeline persistence: save/load/autosave to the local filesystem.

The backend serves a single user on `localhost`. It is not multi-tenant. There is no auth. CORS is open to `http://localhost:5173` and the same origin only.

---

## 2. Stack

- **Python 3.11+** (use `match` statements, structural typing freely)
- **FastAPI** + **uvicorn[standard]**
- **Pydantic v2** for all request/response/config schemas
- **pandas**, **numpy**, **scikit-learn** as the ML core
- **xgboost**, **imbalanced-learn**, **shap**, **lime**, **joblib** for the heavier nodes
- **matplotlib** (Agg backend) for plots — convert to base64 PNGs server-side
- **structlog** for structured logging
- **pytest** + **pytest-asyncio** for tests
- **ruff** + **mypy** (strict) for linting and typing
- **uv** for package management; lockfile committed

Avoid: Flask, Django, Celery (overkill for single-user), tensorflow/pytorch (out of scope), seaborn (matplotlib is enough).

---

## 3. Directory layout

```
backend/athena/
├── __init__.py
├── main.py                   # FastAPI app: include_router, CORS, startup/shutdown
├── config.py                 # Settings via pydantic-settings; reads ATHENA_* env vars
│
├── api/
│   ├── __init__.py
│   ├── pipelines.py          # POST /run, /save, /load, /export, /autosave
│   ├── runs.py               # GET /runs/{id}, POST /runs/{id}/cancel, GET artifacts
│   ├── ws.py                 # WS /ws/runs/{id} — per-run event stream
│   └── nodes.py              # GET /nodes — registry metadata for the frontend (debug aid)
│
├── core/
│   ├── __init__.py
│   ├── registry.py           # NODE_REGISTRY: type -> NodeHandler
│   ├── handler.py            # NodeHandler protocol, ExecutionContext dataclass
│   ├── executor.py           # async DAG executor with cancellation + cache
│   ├── dag.py                # topo sort, cycle detection (canonical impl)
│   ├── cache.py              # content-addressed artifact cache (per-run + persistent)
│   ├── codegen.py            # PipelineSpec -> python script | notebook | json
│   └── events.py             # event broker pattern: executor publishes, WS subscribes
│
├── nodes/
│   ├── __init__.py           # imports all categories so they self-register
│   ├── data.py               # csv/excel/json/db/api/synth/merge/sample
│   ├── quality.py            # imputer/dup/outlier/type/validator
│   ├── feature.py            # selector/ohe/label/scaler/featgen/tfidf/embedding/date/featimpsel/pca
│   ├── balance.py            # smote/under/over/classweight
│   ├── split.py              # train_test/train_val_test/cv
│   ├── model.py              # lin_reg/log_reg/dtree/rf/xgb/svm/knn/nb/mlp
│   ├── advanced.py           # automl/hp_tuner/pipeline_wrap/custom_code
│   ├── ensemble.py           # voting/stacking/blending
│   ├── eval.py               # metrics/conf_matrix/roc/feat_imp_viz/residual
│   ├── interp.py             # shap/lime/debugger
│   ├── deploy.py             # predict/api_gen/csv_export/model_saver/report_gen
│   └── monitor.py            # drift/perf
│
├── schemas/
│   ├── __init__.py
│   ├── pipeline.py           # PipelineSpec, NodeSpec, EdgeSpec — root §4.1 mirror
│   ├── events.py             # WS event Pydantic models
│   └── artifacts.py          # ArtifactPreview discriminated union
│
├── storage/
│   ├── __init__.py
│   ├── files.py              # save/load .athena files
│   └── autosave.py           # autosave dir at ~/.athena/autosave/
│
└── utils/
    ├── plotting.py           # matplotlib -> base64 PNG helper
    ├── dataframes.py         # safe preview, dtype JSON-ification
    └── tracing.py            # structlog setup, per-run trace ids
```

---

## 4. The handler contract

Every node is a function with this shape, registered against the `NODE_REGISTRY` by `type`:

```python
# core/handler.py
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
import pandas as pd

@dataclass
class ExecutionContext:
    node_id: str
    node_type: str
    config: dict[str, Any]
    inputs: list[Any]              # ordered, same length as registry inputs
    run_id: str
    cache_dir: Path
    logger: structlog.BoundLogger  # logger.info(...) -> emits node_log WS event

@dataclass
class HandlerResult:
    outputs: list[Any]                       # ordered, same length as registry outputs
    preview: ArtifactPreview | None = None   # what to send in node_finish
    metrics: dict[str, float] = field(default_factory=dict)

class NodeHandler(Protocol):
    inputs: list[PortSpec]
    outputs: list[PortSpec]
    config_schema: type[BaseModel]           # Pydantic model for validating config

    def __call__(self, ctx: ExecutionContext) -> HandlerResult: ...
```

A handler is a callable class defined once with the node SDK (`athena.sdk`). The `@node` decorator holds everything the frontend needs (label, category, ports, form hints, export template), so there is no second registry:

```python
# nodes/quality.py
from athena.sdk import Port, node, ui

@node(
    "imputer", label="Missing Value Imputer", category="quality",
    description="Fill missing values",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
    fields={"strategy": ui("Strategy"), "fill_value": ui("Fill Value")},   # labels/widgets; options come from Literal
    code=_CODE_IMPUTER,                    # export template, or export_note="why it can't be exported"
)
class ImputerHandler:
    class Config(BaseModel):
        strategy: Literal["mean", "median", "mode", "constant", "knn"] = "mean"
        fill_value: str = "0"
        cols: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        # ... real sklearn logic ...
        return HandlerResult(
            outputs=[df_imputed],
            preview=preview_dataframe(df_imputed),
            metrics={"rows": len(df_imputed), "missing_filled": n_filled},
        )
```

**Rules for handlers:**
- Validate config via the Pydantic schema; raise `ValueError` with a clean message on bad input. The executor catches and converts to a `node_finish: error` event.
- Don't print. Use `ctx.logger`. Each call becomes a `node_log` WS event.
- Return artifacts in the **declared output order**. Downstream nodes index by port number.
- For long operations, periodically check `ctx.cancelled()` (provided by executor) and return early to enable graceful stops.
- Don't keep references to inputs after returning — let them be freed.

---

## 5. Executor

`core/executor.py`. Async, single-pipeline-at-a-time, in-process.

```python
async def execute(spec: PipelineSpec, run_id: str, broker: EventBroker,
                  start_from: list[str] | None = None) -> RunResult:
    order = topo_sort(spec.nodes, spec.edges)        # raises on cycle
    artifacts: dict[tuple[str, int], Any] = {}       # (node_id, port_idx) -> artifact

    for node_id in order:
        if cancelled(run_id):
            await broker.publish(run_id, RunFinish(status="cancelled"))
            return

        node = spec.node(node_id)
        if start_from and not is_descendant_of(node_id, start_from, spec):
            # reuse cached artifacts; skip handler
            continue

        await broker.publish(run_id, NodeStart(node_id=node_id))
        ctx = build_context(node, artifacts, spec.edges, run_id, broker)
        cache_key = compute_cache_key(node, ctx.inputs)

        try:
            cached = cache.get(cache_key)
            if cached is not None:
                result = cached
            else:
                result = await run_in_threadpool(handler_for(node.type), ctx)
                cache.set(cache_key, result)

            for i, art in enumerate(result.outputs):
                artifacts[(node_id, i)] = art

            await broker.publish(run_id, NodeFinish(
                node_id=node_id, status="success",
                preview=result.preview, metrics=result.metrics,
                duration_ms=...,
            ))
        except Exception as exc:
            await broker.publish(run_id, NodeFinish(
                node_id=node_id, status="error",
                error=ErrorPayload(message=str(exc), traceback=traceback.format_exc()),
            ))
            await broker.publish(run_id, RunFinish(status="error"))
            return

    await broker.publish(run_id, RunFinish(status="completed"))
```

Key requirements:
- **Heavy work runs in `run_in_threadpool`** so the FastAPI event loop stays responsive (WS messages keep flowing). For CPU-bound ML, use `anyio.to_thread.run_sync` or `concurrent.futures.ThreadPoolExecutor`. Don't block the loop.
- **Cancellation** is cooperative. `POST /api/runs/{id}/cancel` flips a flag the executor checks between nodes. In-flight node finishes naturally (we don't kill threads — too dangerous with C extensions).
- **Single run at a time.** A second `POST /run` while one is active returns 409.
- **Cache key** = SHA256 of `(node.type, canonical_json(node.config), [parent_cache_keys])`. Skip the handler if the key hits.
- **Errors are user errors by default.** Wrap each handler call. Internal executor exceptions (KeyError, etc.) surface as 5xx and a different WS close code so the frontend can distinguish.

---

## 6. WebSocket protocol

`api/ws.py` exposes `WS /ws/runs/{run_id}`. The connection subscribes to the broker for that run id. All messages are JSON, one event per message. Pydantic models in `schemas/events.py`:

```python
class NodeStart(BaseModel):
    type: Literal["node_start"] = "node_start"
    node_id: str

class NodeLog(BaseModel):
    type: Literal["node_log"] = "node_log"
    node_id: str
    level: Literal["debug", "info", "warn", "error"]
    msg: str
    ts: datetime

class NodeFinish(BaseModel):
    type: Literal["node_finish"] = "node_finish"
    node_id: str
    status: Literal["success", "error"]
    duration_ms: int
    preview: ArtifactPreview | None = None
    metrics: dict[str, float] = {}
    error: ErrorPayload | None = None

class RunFinish(BaseModel):
    type: Literal["run_finish"] = "run_finish"
    status: Literal["completed", "error", "cancelled"]
```

If a client connects after the run has already finished, send the buffered final state and close. Buffer the last 200 events per run for ~10 minutes.

---

## 7. The node registry

`@node` (in `athena/sdk/node.py`) registers into `core/registry.py`: `NODE_REGISTRY` (type → handler instance), `NODE_META` (type → `NodeMeta`) and `CATEGORIES`. Built-in nodes register when `athena.nodes` is imported; plugins will register through the `athena.nodes` entry point (roadmap 0.5). A plugin that introduces a category calls `register_category()` first.

`GET /api/nodes` serves `node_spec()` for every node plus the categories. **The frontend builds its library and inspector forms from this response**; it has no node definitions of its own.

Rules:
- Labels, widgets and options: put them in `fields={...: ui(...)}`. Prefer `Literal[...]` types so options come from the type and validation matches the form.
- `available=False, unavailable_reason=...` hides a not-yet-implemented node from the library while keeping old pipelines loadable. Prefer not adding stubs at all.
- `tests/test_node_specs.py` checks every node: UI hints match `Config`, select defaults are among the options, ports are unique, and export templates fill from defaults.

`custom_code` executes user-supplied Python. It must move to the worker process with the rest of execution (roadmap 0.4); until then it `exec`s in a restricted namespace inside the API process, which is the main reason for 0.4.

---

## 8. Code generation

`core/codegen.py`. Three target formats:

### Python script
Goal: a `.py` file that, when run with the same Python env, produces the same artifacts as Athena's executor. Structure:

```python
# Generated by Athena
# Pipeline: <name or "untitled">
# Generated at: <iso ts>

import pandas as pd
import numpy as np
from sklearn... import ...
# ... imports collected from per-node templates ...

# --- Node n1: CSV Loader ---
df_n1 = pd.read_csv("data.csv", sep=",", encoding="utf-8")

# --- Node n2: Missing Value Imputer (mean) ---
from sklearn.impute import SimpleImputer
imputer_n2 = SimpleImputer(strategy="mean")
df_n2 = pd.DataFrame(imputer_n2.fit_transform(df_n1), columns=df_n1.columns)

# --- Node n4: Train/Test Split ---
from sklearn.model_selection import train_test_split
X_n4, y_n4 = df_n3.drop(columns=["target"]), df_n3["target"]
X_train_n4, X_test_n4, y_train_n4, y_test_n4 = train_test_split(
    X_n4, y_n4, test_size=0.2, random_state=42, stratify=y_n4
)
# ...
```

Each node has a `code_template(node, var_in, var_out)` method that returns its lines. The codegen module:
1. Topo-sorts the DAG.
2. Calls each node's template, accumulating imports and body lines.
3. Deduplicates imports.
4. Joins with section headers.

Snapshot-test the output for each starter template (`tests/test_codegen.py`).

### Jupyter notebook
Use `nbformat`. One markdown cell per node (label + description from registry), one code cell per node (the same lines as the script). Keeps the same variable naming convention.

### Pipeline JSON
Pretty-print the `PipelineSpec` with `indent=2, sort_keys=False`.

---

## 9. Persistence

`.athena` files = the `PipelineSpec` JSON, saved to a path the user provides (no magic location). `POST /api/pipelines/save` validates the path is writable, the parent dir exists, and writes atomically (write to `.tmp`, then `os.replace`).

Autosave: `~/.athena/autosave/latest.athena` written every 10s when the in-memory pipeline differs from the last saved version. Keep the previous 5 autosaves rotated (`autosave-1.athena`, etc.) for recovery.

`~/.athena/` layout:
```
~/.athena/
├── cache/<run_id>/        # ephemeral artifact cache, cleared on app shutdown
├── autosave/              # rotated autosaves
├── settings.json          # user prefs (theme override, cache size)
└── recent.json            # last 10 opened pipeline paths
```

---

## 10. Configuration

`config.py` — single Settings class (pydantic-settings). All env vars prefixed `ATHENA_`:

| Var | Default | Meaning |
|---|---|---|
| `ATHENA_HOST` | `127.0.0.1` | Bind address |
| `ATHENA_PORT` | `8000` | |
| `ATHENA_DATA_DIR` | `~/.athena` | Cache, autosave, settings root |
| `ATHENA_NODE_TIMEOUT_S` | `300` | Per-node soft timeout |
| `ATHENA_CACHE_MAX_GB` | `2` | Cache eviction trigger (LRU) |
| `ATHENA_LOG_LEVEL` | `INFO` | structlog level |
| `ATHENA_ALLOW_CUSTOM_CODE` | `true` | Disables `custom_code` if false |

No environment variable should ever change the **on-the-wire schema**. Configuration affects behavior, not contracts.

---

## 11. Logging & errors

- `structlog` JSON logs to stdout. Each log line includes `run_id` and `node_id` when in scope (use `structlog.contextvars.bind_contextvars`).
- Don't log dataframe contents — log shapes, dtypes, column names at most.
- Don't `except Exception: pass` anywhere. Either re-raise or convert to a typed error.
- HTTP errors return `{ "detail": "...", "code": "STABLE_ERROR_CODE" }`. Frontend matches on `code`, not on message text.

Error codes (initial set):
- `PIPELINE_VALIDATION_FAILED`
- `PIPELINE_HAS_CYCLE`
- `RUN_ALREADY_IN_PROGRESS`
- `RUN_NOT_FOUND`
- `NODE_TYPE_UNKNOWN`
- `CONFIG_INVALID`
- `FILE_NOT_FOUND`
- `FILE_NOT_WRITABLE`

---

## 12. Testing

```
backend/tests/
├── test_dag.py               # topo sort + cycle detection edge cases
├── test_executor.py          # cancellation, error halts, caching, partial run
├── test_codegen.py           # snapshot tests for starter templates
├── test_handlers/
│   ├── test_csv_loader.py
│   ├── test_imputer.py
│   ├── test_rf.py            # one file per non-trivial handler
│   └── ...
├── test_api_pipelines.py     # FastAPI TestClient — happy paths + 4xx cases
├── test_ws.py                # async WS flow with a mocked executor
└── fixtures/
    ├── data/iris.csv
    ├── data/wine.csv
    └── pipelines/             # sample .athena files for tests
```

Run with `uv run pytest -q`. Coverage target: 80% on `core/`, 60% overall (handlers don't all need exhaustive tests, but the executor and codegen do).

---

## 13. Performance & resource limits

- DataFrame previews: cap at 50 rows × 50 cols. Use `df.head(50).iloc[:, :50]`.
- Plot images: render at 600×400 dpi=80, JPEG isn't allowed (lossy), PNG only. Most plots stay under 50KB.
- Memory: assume single-node datasets fit in RAM. If a `csv_loader` reads >1GB, log a warning and proceed.
- The cache is best-effort. On low disk, evict LRU entries until under `ATHENA_CACHE_MAX_GB`.

---

## 14. Security posture

This is a **local** app. We trust the user. But:
- Bind to `127.0.0.1` by default. Document loudly that changing `ATHENA_HOST` to `0.0.0.0` exposes the user's filesystem to anyone on the network.
- `csv_loader` and friends accept arbitrary filesystem paths — that's intentional. No path sandboxing.
- `custom_code` runs `exec()` — gated behind `ATHENA_ALLOW_CUSTOM_CODE` and shown with a warning in the UI.
- CORS allowlist: `http://localhost:5173`, `http://127.0.0.1:5173`. Nothing else.
- No auth. If a future "share" feature is requested, that's a new product — not a config flag.

---

## 15. What not to do

- Don't introduce a database. Pipelines are files; runs are ephemeral.
- Don't run the executor in a subprocess or container in v1. Threadpool is enough.
- Don't pre-emptively support distributed execution, GPU scheduling, or queueing.
- Don't let `custom_code` import `os.system` without it being obvious — but also don't pretend a sandbox exists when it doesn't. Be honest with the user.
- Don't add cloud SDKs (boto3, gcloud) unless a specific node needs them, in which case make it an extras dep.
- Don't return `Any` from typed functions. If something is genuinely dynamic (artifacts, configs), use a proper union type.
- Don't tightly couple the executor to FastAPI. The executor takes a `broker` interface; tests can swap it for an in-memory list.
