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
│   ├── pipelines.py          # POST /run, /save, /load, /export, /code (per-node code view), /autosave
│   ├── subflows.py           # GET/PUT /api/subflows, DELETE /api/subflows/{name} (the subflow library)
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

Two parts, single-pipeline-at-a-time:

- **`runtime/engine.py`** walks the DAG and calls handlers. It is synchronous and runs **only inside a worker process** (`runtime/worker.py`), one fresh process per run. A warm standby worker has already imported the nodes, so runs start fast.
- **`core/executor.py`** is the supervisor inside the API server. It hands the run to a worker, relays the worker's events (sent over a `Pipe`, so they survive the worker dying) to the broker, and enforces per-node timeouts (`ATHENA_NODE_TIMEOUT_S`), hard cancellation after a grace period, and crash reporting.

The sketch below shows the engine's logic; the real code lives in `runtime/engine.py`.

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
- **Node code never runs in the API process.** Handlers, `custom_code` included, run in the worker. Don't import or call handlers from API routes.
- **Cancellation** is cooperative first: the worker checks a flag between nodes, and handlers can poll `ctx.cancelled()`. If the in-flight node hasn't finished `CANCEL_GRACE_S` after Stop, the supervisor kills the worker and reports the node as cancelled.
- **Timeouts and crashes are user-visible errors**: a node over `ATHENA_NODE_TIMEOUT_S`, or a worker that dies (segfault, `os._exit`, out of memory), becomes `node_finish: error` + `run_finish: error`, and the run slot is freed.
- **Logs**: `ctx.logger` is a `NodeLogger`; every call becomes a `node_log` WS event.
- **Single run at a time.** A second `POST /run` while one is active returns 409.
- **Cache key** = SHA256 of `(node.type, canonical_json(node.config), [parent_cache_keys], fingerprint of local paths in the config)`, shared across runs (`core/cache.py`, store in `cache/store/`, per-run `index.json`). Skip the handler if the key hits and the node is reusable (`node.cache` and `@node(reusable=True)`, the default). `reusable=False` nodes (file writers, model registration, SQL/API/cloud sources, custom code) always execute and are keyed by a content digest of their outputs (no path fingerprint: their paths are outputs), so downstream reuse follows the data.
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

`@node` (in `athena/sdk/node.py`) registers into `core/registry.py`: `NODE_REGISTRY` (type → handler instance), `NODE_META` (type → `NodeMeta`) and `CATEGORIES`. Built-in nodes register when `athena.nodes` is imported; plugins register through the `athena.nodes` entry point (see Plugins below). A plugin that introduces a category calls `register_category()` first.

`GET /api/nodes` serves `node_spec()` for every node plus the categories. **The frontend builds its library and inspector forms from this response**; it has no node definitions of its own.

Rules:
- Labels, widgets and options: put them in `fields={...: ui(...)}`. Prefer `Literal[...]` types so options come from the type and validation matches the form.
- `available=False, unavailable_reason=...` hides a not-yet-implemented node from the library while keeping old pipelines loadable. Prefer not adding stubs at all.
- `tests/test_node_specs.py` checks every node: UI hints match `Config`, select defaults are among the options, ports are unique, and export templates fill from defaults.

`custom_code` executes user-supplied Python. It runs in the worker like every handler, and is refused when `ATHENA_ALLOW_CUSTOM_CODE=false`.

### Plugins

`athena/plugins.py: load_plugins()` imports the built-ins (`athena.nodes`, `athena.connectors`) and every package declaring the `athena.nodes` / `athena.connectors` entry points. It runs once per process: in the API server (at import of `main`, `api/nodes`, `codegen`) and in each worker. A plugin that fails to import is recorded (`GET /api/plugins`) and skipped. The authoring guide is `docs/PLUGINS.md`.

### Connectors and connections

- **Connector** (`athena/sdk/connector.py`, `@connector`): a type of external system. It declares a Pydantic `Config` (`SecretStr` fields are secrets) and implements `test`, `list` and `read`. Built-in: `sql` (`connectors/sql.py`, SQLAlchemy; DB drivers are optional extras `postgres`, `mysql`, `duckdb`, `mssql`).
- **Connection** (`connectors/store.py`): a user's saved, named configuration in `<data_dir>/connections.json`. Secret fields hold only a marker there; the values live in the OS keychain (`connectors/secrets.py`, `keyring`) or are `env://VAR` references resolved at use time.
- Nodes take a connection by **name** (`ui(widget="connection", connector="sql")`) and resolve it in the worker with `resolve_connection(name)`. Never put credentials in node config, specs, logs, previews or exported code; exports read them from environment variables.
- API: `GET /api/connectors`, `GET/PUT /api/connections`, `GET/DELETE /api/connections/{name}`, `POST /api/connections/test`, `GET /api/connections/{name}/resources`. Secrets are write-only: responses say only whether one is set (and show `env://` references).
- Tests use `secrets.set_store(MemoryStore())`; never touch the real keychain in tests.

### Experiment tracking and the model registry (MLflow)

- `athena/tracking/` (optional extra `athena-backend[mlflow]`; MLflow is imported lazily, so Athena runs without it).
- **Destination:** `session.mlflow_session(connection)` points MLflow at a saved `mlflow` connection or, for `""`, the local store (`<data_dir>/mlflow/mlflow.db` + `artifacts/`). MLflow state is process-global: always go through the session, which restores it.
- **Observer:** `runtime/observers.py` is the generic hook (`on_run_start`, `on_node_finish`, `on_run_finish`, optional `abandon`). `tracking/observer.py` logs a tracked run: params `<node_id>.<field>`, metrics `<node_id>.<metric>`, `athena/pipeline.json` + `athena/pipeline.py`, and every `model` output (cloudpickle, pinned pip requirements). Observer errors become `run_info` warnings and close the MLflow run as FAILED; they never fail the pipeline. If the supervisor kills a worker, it marks the tracked run KILLED/FAILED.
- **Nodes:** `mlflow_register` (into the tracking destination, reusing the model the run already logged; local store when untracked) and `mlflow_load` (by alias or version, from any destination).
- **API:** `GET /api/tracking/status`, `POST /api/tracking/local/init` (the one-time ~20 s store creation), `GET /api/tracking/experiments`, `GET /api/tracking/runs`.
- Tests use the `mlflow_local_store` fixture (conftest): one template store per session, copied per test; creating a store costs ~20 s.

### Data, storage and boosting

- `nodes/files.py`: Parquet Loader, SQL Transform (DuckDB, a private in-memory connection per run; inputs registered as `in1`/`in2`), Cloud File Loader. `connectors/storage.py`: the `storage` connector (fsspec; drivers are extras `s3`, `gcs`, `azure`). `read_frame` is the one place that turns a path + format into a DataFrame.
- Base dependencies include `pyarrow`, `duckdb`, `fsspec` and `lightgbm` (all lean). CatBoost and Optuna are extras.
- `nodes/boosting.py`: LightGBM and CatBoost nodes share `_fit`: early stopping on X_val/y_val when connected, otherwise the common fit/tune path. Optuna lives in `nodes/model.py` (`_optuna_search`) as a method of the HP Tuning Config node.
- Export functions that need connection details read only non-secret settings (`store.get_connection`); credentials always come from environment variables in exported code.

### REST APIs (dlt)

- `connectors/http_api.py` (extra `athena-backend[api]`): the `http_api` connector and `fetch_frame`, which runs dlt's declarative REST source into a DuckDB file in a short-lived temp folder (dlt's paths are deep; Windows caps paths at 260 characters) and reads the root table back with DuckDB. `nodes/api.py` is the API Fetch node.
- **No telemetry:** the module sets `RUNTIME__DLTHUB_TELEMETRY=false` before dlt loads; codegen's `PRELUDE` does the same at the top of any exported script that imports dlt.
- Tests use a local mock API (`tests/test_api_ingestion.py`) covering every pagination style and auth method; never call real APIs in tests.
- **SaaS apps:** `connectors/saas_presets.py` is data (base URL, auth, paginator, resources per app); `connectors/saas.py` generates one connector per preset (`saas_<app>`, only that app's credentials) and builds the dlt config; `nodes/api.py: saas_fetch` reads it. Stripe and Zendesk page with "has more + cursor/last id", which `connectors/saas_paginator.py: _AthenaHasMorePaginator` handles (imported only when fetching; copied verbatim into exports). Add an app by adding a preset and a mock in `tests/test_saas.py` that is strict where the real API is.
- Widgets: `connection` takes `connector="a,b"` (any of several types); `resource` with `connection_field=` lists the chosen connection's `list()` (GET `/api/connections/{name}/resources`); `code` with `language="python"|"sql"` is a code editor (Custom Code, SQL Query, SQL Transform).

### Subflows

- `core/subflows.py`: `SubflowConfig` (inner `nodes`/`edges`, `inputs`/`outputs` mapping to inner ports) and `expand(spec, start_from)`, which replaces each subflow by its inner nodes (`<subflow>.<inner>`, nested ones too, up to 8 levels) and rewires boundary edges. It runs in the run endpoint (before the cycle check), in `run_spec` (a no-op when already expanded) and in `codegen.build_sections`; nothing downstream knows subflows exist.
- `storage/subflows.py`: the library in `<data_dir>/subflows/<slug>.json` (validated on save; a broken file is skipped in listings).

### Serving

- `serving/bundle.py`: `bundle_from_run(name, spec, run_id, node_id, port)` loads the model from the run (`core/artifacts.py`), finds its training features by following model inputs back to an `X_train` input (`training_source`), lists upstream preprocessing nodes (categories quality/feature/balance) that the served model does not replay, and writes `<data_dir>/models/<slug>/`. Requirements come from the modules the model's pickle actually references (a recording `Unpickler`), mapped to installed distributions and pinned; `needs_athena` flags models pickled with Athena's own classes. Example values are medians / modes, never real rows.
- `serving/templates.py`: the standalone `service.py` (FastAPI), BentoML service, bentofile, Dockerfile and README. Keep them free of Athena imports.
- `serving/endpoints.py`: each endpoint is `python service.py --exit-with-parent` in its own process on a free 127.0.0.1 port (user models never load in the API process). Its stdin is a pipe Athena holds, so the service exits when Athena does, even after a crash; `stop_all()` runs at shutdown too. API: `api/serving.py` (`/api/serving/bundles`, `/api/serving/endpoints/{slug}`, `.../predict` for the test console).

### Run outputs and profiling

- The worker pickles every node's result into the run's cache folder (`<data_dir>/cache/<run_id>/`) and records `node_id -> cache key` in `index.json`, whether or not `node.cache` is on (that flag only decides whether a cached result is *reused*). `core/artifacts.py: load_output()` reads them back in the API process; it deserialises results, never runs handlers.
- `GET /api/runs/{run}/artifacts/{node}/{port}?format=csv|parquet`: tables as CSV/Parquet, reports as JSON, models/transformers as joblib. `GET /api/runs/{run}/profile/{node}/{port}?target=`: the profile. Both 404 with `ARTIFACT_NOT_FOUND` once the run's folder is gone.
- `athena/profiling.py` is pure pandas/sklearn: column kinds, statistics and histograms, insights (`severity`, `code`, `column`, `message`) and mutual information with the target. It samples frames over 100,000 rows (20,000 for mutual information) and returns strictly JSON-safe values (no NaN/inf).

### Calibration and decision thresholds

- `nodes/calibration.py`: Probability Calibration (`CalibratedClassifierCV`; `FrozenEstimator` on the validation set, else a clone over stratified k-fold on train), Calibration Curve, and Decision Threshold (wraps the fitted model in `FixedThresholdClassifier(FrozenEstimator(model))`, so probabilities are unchanged).
- `_athena_tuning_scores` and `_athena_threshold` are self-contained functions that codegen copies verbatim into exports (`core/export_helpers.py`), so the search is identical in Athena and the script. Ties take the middle of the tied threshold range; precision is 0 where nothing is predicted positive.
- Tuning never touches the test set. Without `X_val`/`y_val`, scores are out-of-fold predictions on the training set.

### statsmodels and PR-AUC

- `nodes/stats.py` (extra `athena-backend[stats]`): `sm_ols` and `sm_logit`. `_StatsOLS` / `_StatsLogit` (on `_StatsBase(BaseEstimator)`) are real scikit-learn estimators, so `clone()`, Metrics, Calibration and Decision Threshold work with them. They're self-contained and copied verbatim into exports; `HELPER_DEPS` in `core/export_helpers.py` pulls in a helper's base class.
- PR-AUC is `average_precision_score` for the second class (binary) or the macro average over classes; the Metrics node and `pr_curve` (in `nodes/calibration.py`) agree.

### Forecasting and clustering

- Categories `forecast` ("Time Series") and `cluster` ("Clustering") are built in (`core/registry.py`); the frontend has `--cat-forecast` / `--cat-cluster`.
- `nodes/forecast_core.py` holds the forecasting logic as self-contained `_athena_*` functions (series parsing, season inference, the four methods, metrics, forecast table, backtest, chronological split). `nodes/forecast.py` adds config, logs and plots. Exports call the same functions, copied verbatim; `HELPER_DEPS` pulls in their dependencies transitively.
- One series per table, regular frequency; `_athena_series` refuses duplicates, missing values and gaps with a fix. Text date columns may arrive as pandas' string dtype, not `object`: check both (`_athena_date_col`).
- ETS uses statsmodels' `ETSModel` on a `pd.Series` (its intervals break on a bare ndarray in 0.15). `gbm_lags` models first differences recursively with `HistGradientBoostingRegressor(random_state=0)`; it has no intervals. Metrics omit keys that are undefined (MAPE with all-zero actuals, MASE with a flat train) instead of sending NaN.
- `nodes/cluster.py`: K-Means/Hierarchical/DBSCAN add a `cluster` column (noise = -1); silhouette excludes noise and samples 5,000 rows with a fixed seed. Cluster colours follow the cluster id.

### AutoML

`nodes/automl.py` (optional extra `athena-backend[automl]`, FLAML). The output model is FLAML's `AutoML` object (it keeps FLAML's preprocessing, so downstream nodes call it like any estimator). Task and metric are resolved explicitly before calling FLAML so scores can be reported as scores, not losses. FLAML's own MLflow logging is disabled (`mlflow_logging=False`); Athena's tracking observer owns the run. FLAML's logger doesn't propagate: attach handlers to `flaml.automl.logger` directly.

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
| `ATHENA_CACHE_MAX_GB` | `2` | Cache eviction trigger (LRU, after each run; the current run's entries are kept) |
| `ATHENA_KEEP_CACHE` | `false` | Keep cached node results across restarts |
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
