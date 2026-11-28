# Athena roadmap

Athena is becoming an open-source, visual ML engineering platform: an open alternative to SageMaker Canvas that covers the whole lifecycle (data → features → training → evaluation → registry → serving → monitoring) and never hides the code.

This file is the plan of record. Each phase ships something usable on its own. The ideas behind it are in the product brief (`open_source_visual_ml_platform.md`, kept outside the repo); this roadmap is the version we build against.

## Product decisions (made 2026-11-26)

1. **Local-first now, server mode later.** `pip install athena && athena` must keep working on a laptop with no infrastructure. Athena connects *out* to tools the user already runs (MLflow, warehouses, Kubernetes, model APIs) with the user's own credentials. A multi-user server mode (Postgres, auth, RBAC) is a later phase that adds to the local mode instead of replacing it.
2. **Foundation before features.** Integrations land as plugins on top of a stable node SDK, a stable workflow spec and an isolated runtime, not as more hand-edited entries in two registries.
3. **Reuse mature tools, build the experience.** Athena builds the canvas, the workflow spec, the compiler, the plugin and connector SDKs and the UX. It integrates MLflow, DuckDB, SQLAlchemy, dlt, Optuna/FLAML, BentoML, Evidently, Feast, Ray and KServe instead of re-implementing them.
4. **Visual-first, not visual-only.** Every node shows its configuration, the code it generates, its runtime and its logs. Every workflow exports to code that runs without Athena.
5. **Apache-2.0 core, bring-your-own-subscription connectors.** Paid products (Snowflake, Databricks, SageMaker, Pinecone, W&B, …) are connector plugins that use the user's credentials. Each connector records its license and the license of the library it wraps.

## Where the prototype stands (audit, 2026-11-26)

| Area | State |
|---|---|
| Canvas, typed ports, run over WebSocket, previews | Works |
| Node registry | **Two hand-maintained copies** (`frontend/src/registry/nodeRegistry.ts`, 1,114 lines, and the backend handlers). The backend has no port or UI metadata. 12 of 83 nodes disagree on defaults or fields. |
| Stub nodes | 7 of 83 appear in the library but raise `NotImplementedError`: `db_connector`, `api_fetch`, `embedding`, `automl`, `blending`, `lime`, `api_gen` |
| Execution | Handlers run in the API server's thread pool. `custom_code` calls `exec()` inside the API process. |
| Caching | The cache directory is per run (`cache/<run_id>`), so nothing is reused across runs |
| Code export | Templates live apart from the nodes; most nodes export as `(no template)`. The `header=True` crash is fixed in PR #1. |
| Tests | 7 stale tests in `tests/test_handlers/test_rf.py` (they pass 2 inputs to 5-port model nodes) |
| Frontend | Error toasts are cleared after 0 ms (`uiStore.ts`), so users never see them |

## Phase 0: Foundation (in progress)

Goal: make adding a node, connector or runtime a one-place change, and stop running user code in the API process.

**Status (2026-11-27):** 0.1, 0.3, 0.4, 0.5 and 0.6 done. 0.2 done (2026-11-27): 88 of 92 nodes export, proven equivalent by tests; the other 4 are unimplemented stubs. 0.7 done (2026-11-28): tests, toast and `max_features` fixed, stubs hidden (4 remain: embedding, blending, lime, api_gen), PR #1 merged. See `docs/PLUGINS.md` for the plugin and connector SDKs.

| # | Deliverable | Done when |
|---|---|---|
| 0.1 | ✅ **Node SDK.** One Python definition per node: type, label, category, description, typed ports, a Pydantic config with UI hints, a handler, and an optional export template. `GET /api/nodes` serves the full spec. The frontend builds its library and inspector forms from it, and `nodeRegistry.ts` stops being a second registry. | A new node needs only a Python file. A test fails if any node's config, ports or UI metadata disagree. |
| 0.2 | ✅ **Export lives on the node.** Each node either supplies its own code template or explicitly declares `exportable=False` with a reason; export inserts that reason as a comment. | A test enforces the declaration for every node. |
| 0.3 | ✅ **Workflow spec v2.** Adds `name`, `metadata`, and per-node `runtime`, `resources`, `retry` and `cache` policy. v1 files load and upgrade automatically. | v1 round-trips; v2 fields are validated. |
| 0.4 | ✅ **Isolated runtime.** Each run executes in a worker process. The API server only schedules work and streams events. Cancellation and per-node timeouts are enforced by the worker; a hung run can be killed. `custom_code` runs only in the worker. | A crashing or looping node can't take the API down. |
| 0.5 | ✅ **Plugin loading.** Nodes and connectors register through Python entry points (`athena.nodes`, `athena.connectors`). The built-ins are declared there too, and are also imported directly so a stale install still works. | An external package adds a node without touching core. |
| 0.6 | ✅ **Connector SDK.** A connector declares a config schema, which fields are secrets, `test()`, `list()` and `read()`/`write()`. Secrets are stored in the OS keychain (`keyring`) and referenced as `secret://<name>`; they never appear in `.athena` files or exports. UI: a Connections panel with a "Test connection" button. | The SQL connector (SQLAlchemy: Postgres, MySQL, SQLite, DuckDB) replaces the `db_connector` stub. |
| 0.7 | ✅ **Debt.** Fix the stale tests, the toast bug and the invalid `max_features='auto'` option; hide stub nodes until they are implemented; merge PR #1. | Both test suites green. |

## Phase 1: ML development platform

- ✅ **MLflow** (2026-11-27): tracked pipelines log params, metrics, models, the pipeline file and its exported script to a local store (`~/.athena/mlflow`) or the user's MLflow server; *Register Model* and *Load Registered Model* nodes; a Runs view with side-by-side comparison. Later: model cards, dataset logging, MLflow UI deep links for the local store.
- **Data:** ✅ (2026-11-27) DuckDB as the local engine (SQL Transform node), Parquet Loader, Object Storage connector + Cloud File Loader (S3/MinIO/R2, GCS, Azure, local through `fsspec`), SQL via the 0.6 connector. ✅ REST API ingestion with dlt (2026-11-28): REST API connector + API Fetch node (all common pagination styles, auth methods, nested JSON), replacing the `api_fetch` stub. ✅ Data profiling (2026-11-28): a Profile view for any table output after a run (schema, per-column statistics and distributions, data-quality findings, target distribution and mutual information) plus downloads of any node output. ✅ SaaS sources (2026-11-28): GitHub, Stripe, HubSpot, Jira, Zendesk and Shopify presets on dlt's REST source (their own connectors with just the credentials each needs, a SaaS Fetch node with a resource dropdown, exportable); presets, not `dlt init` downloads, so installs stay offline. More apps are a preset each. Still to do: Arrow end to end.
- **Models:** ✅ AutoML Search (FLAML, 2026-11-27) replaced the `automl` stub: leaderboard preview, progress logs, tracked leaderboard, exportable. ✅ LightGBM and CatBoost nodes (classifier + regressor, early stopping, exportable) and Optuna as an HP Tuning method (2026-11-27). ✅ Probability calibration and threshold tuning (2026-11-28): Probability Calibration (sigmoid/isotonic), Calibration Curve (reliability diagram, Brier, ECE) and Decision Threshold (F1, balanced accuracy, precision or recall targets, error costs) nodes, tuned on a validation set or out-of-fold predictions, exportable. ✅ statsmodels and PR-AUC (2026-11-28): OLS and Logit nodes with coefficient tables (standard errors, p-values, 95% intervals, robust errors), usable by every downstream node; PR-AUC in the Metrics node and a Precision-Recall Curve node.
- **Tasks:** ✅ (2026-11-28) Forecasting: Time Series Split, Forecaster (seasonal naive, ETS, seasonal ARIMA, gradient boosting on lags; intervals; MAE/RMSE/MAPE/sMAPE/MASE/coverage) and rolling-origin Backtest. Clustering: K-Means (automatic k), Hierarchical, DBSCAN and Cluster Evaluation (silhouette, Davies–Bouldin, Calinski–Harabasz, PCA map, profiles). Starter templates for both. Later: several series per table (grouped forecasting), exogenous regressors.
- **Editor:** ✅ (2026-11-28) Per-node code view (CodeMirror 6: the generated Python for each node and the full script, read-only), code editors for Custom Code and SQL fields, and Tidy layout (dagre, undoable). ✅ Reusable subflows (2026-11-28): group a selection into one node, ungroup, a subflow library; expanded by the backend so running, caching and export are unchanged. ✅ Pipeline diff (2026-11-28): Compare the canvas with any saved version: nodes added/removed/changed (field by field, including execution settings and inside subflows), connection changes and pipeline settings, marked on the canvas until cleared. Phase 1 Editor complete.
- **Reproducibility:** ✅ (2026-11-28) A cache reused across runs (content keys with input-file fingerprints; side-effect and live-source nodes always run but keep downstream cached when their output is unchanged; LRU size limit; optional persistence), a working "Run from here" with a preview of what will run, and the Dataset Snapshot node (content-hashed Parquet).

## Phase 2: Production MLOps

- Packaging and serving: ✅ (2026-11-28) Deploy any trained model from a run as a standalone bundle (FastAPI service, pinned requirements, Dockerfile, BentoML service and bentofile, example request); run it as a local endpoint (its own process, 127.0.0.1, stops with Athena) with a test console. ✅ Serving replays the preprocessing (2026-11-28): preprocessing nodes record what they learned (`HandlerResult.replay`), the bundle chains those steps from the data source to the model and verifies they reproduce the training features exactly, so endpoints take raw rows. ✅ Replay of Outlier clip/flag, String Splitter, Feature Importance Selection, and merges as lookups (2026-11-28). ✅ Build Docker images and Bentos from the Serving window (2026-11-28; the user's own docker / bentoml, in the background, with the log). ✅ Batch inference (2026-11-28): the Batch Predict node scores tables with a packaged model in pipelines and schedules; bundles score files with `service.py --predict-file`.
- Quality gates: ✅ (2026-11-28) Quality Gate node (rules against connected reports; stops the run or warns), Fairness Check node (per-group rates, parity and impact metrics), model cards in deployed bundles with the run's evaluation and gate results.
- Monitoring: ✅ (2026-11-28) Evidently nodes (Data Drift Report, Prediction Drift, Data Quality Report) with reports a Quality Gate can check and Evidently's interactive HTML (opened from the inspector, logged to MLflow); local endpoints log their requests and expose Prometheus metrics; Endpoint Requests turns live traffic into a table to compare with the training data. ✅ Retraining triggered by drift (2026-11-28): Quality Gate `on_fail: skip` with a dataset passthrough, so a scheduled pipeline retrains only when drift is detected.
- Scheduling: ✅ (2026-11-28) Schedules run saved pipelines on cron expressions while Athena runs (no catch-up, never overlapping, history of each run, Run now); export a pipeline as an Airflow DAG or a Dagster job (script + orchestrator file + README). ✅ One task per node in orchestrator exports (2026-11-29): each node is an Airflow task / Dagster op, passing data through a per-run artifact folder.

## Phase 3: Scale and the connector ecosystem

- Execution adapters: ✅ Ray (2026-11-29): a node's runtime (`ray`, `ray:<connection>`) runs it as a Ray task with its resources reserved, joblib work spreading over the cluster; Ray cluster connections. Next: Kubernetes Jobs, remote runners; KServe deployments.
- Deep learning nodes: PyTorch, Hugging Face Transformers (fine-tuning, embeddings), ONNX export.
- GenAI: LLM provider connectors (OpenAI, Anthropic, Gemini, Bedrock, Azure OpenAI, Mistral, Ollama, vLLM) with token and cost tracking; RAG building blocks; vector stores (Qdrant, Chroma, pgvector, Milvus, Pinecone); LLM evaluation (groundedness, relevance).
- Warehouses and SaaS: Snowflake, BigQuery, Databricks, Redshift; Airbyte connectors; Feast feature store.
- Lineage: OpenLineage events; OpenMetadata integration.

## Phase 4: Server mode

Postgres metadata store, object storage for artifacts, Redis queue, a pool of execution workers, users and workspaces, RBAC, audit log, SSO, dev/staging/prod environments, a Helm chart. The local single-user mode keeps working.

## Phase 5: Ecosystem

Plugin index, AI-assisted workflow generation (output passes the same validator as hand-built workflows), notebook-to-workflow import, community nodes, a compatibility and license matrix.

## Not doing (for now)

- Rebuilding orchestration, tracking, serving or feature stores that mature projects already provide.
- Cloud-hosted Athena or an Athena account. Every integration uses the user's own infrastructure and credentials.
- Running user code in the API server process, in any phase.
