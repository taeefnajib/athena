<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo-light.png">
    <img alt="Athena" src="docs/assets/logo-light.png" width="420">
  </picture>
</p>

<p align="center">
  <b>Build, run and ship machine-learning pipelines visually, on your own machine.</b><br>
  An open-source alternative to SageMaker Canvas: wire nodes on a canvas, run real pandas, scikit-learn and XGBoost underneath, and export clean Python.
</p>

<p align="center">
  <a href="#setup"><img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="#setup"><img alt="React 18" src="https://img.shields.io/badge/react-18-61DAFB?logo=react&logoColor=black"></a>
  <a href="https://fastapi.tiangolo.com"><img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white"></a>
  <a href="https://scikit-learn.org"><img alt="scikit-learn" src="https://img.shields.io/badge/ML-scikit--learn%20%7C%20XGBoost-F7931E?logo=scikitlearn&logoColor=white"></a>
  <a href="#security-note"><img alt="Local-first, no telemetry" src="https://img.shields.io/badge/local--first-no%20telemetry-2ea44f"></a>
  <a href="https://github.com/taeefnajib/athena/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/taeefnajib/athena?style=flat&logo=github"></a>
</p>

<p align="center">
  <a href="#setup">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#screenshots">Screenshots</a> ·
  <a href="docs/ROADMAP.md">Roadmap</a> ·
  <a href="docs/PLUGINS.md">Plugins</a>
</p>

<p align="center">
  <img alt="Loading a template, running it, and inspecting the results in Athena" src="docs/assets/demo.gif" width="100%">
</p>

---

## Features

- **Visual pipelines that really run.** Drag nodes from a library of 100+ (loaders, cleaning, feature engineering, models, evaluation, explainability, forecasting, clustering), connect typed ports and click **Run**. Every node runs real Python in a worker process, and its status reflects what actually happened.
- **Inspect everything.** Data previews and full profiles of any table, metrics, plots, logs, and the exact Python each node becomes.
- **Export clean code.** A standalone Python script or Jupyter notebook that follows your graph, tested to produce the same results as Athena. Also exports Airflow DAGs and Dagster jobs.
- **Connect to your data.** Databases (PostgreSQL, MySQL, SQL Server, SQLite, DuckDB), files, cloud storage, SaaS apps and REST APIs, with credentials kept in your OS keychain.
- **AutoML and tuning.** FLAML AutoML search, Optuna tuning, LightGBM / CatBoost / XGBoost, calibration and decision thresholds.
- **Track and register.** Optional MLflow experiment tracking and model registry, local or remote.
- **Serve and monitor.** Package a model and start a local prediction endpoint with Prometheus metrics and request logs; Evidently drift and data-quality reports; quality gates, fairness checks and model cards.
- **Automate.** Cron schedules for saved pipelines, with retraining only when the data drifts.
- **Fast iteration.** A content-addressed cache, "Run from here", subflows you can reuse, version comparison and dataset snapshots.
- **Local-first.** No account, no cloud, no telemetry. Light and dark themes.

## Screenshots

<table>
  <tr>
    <td width="50%"><img alt="A completed classification pipeline" src="docs/assets/canvas.jpg"><br><sub><b>Canvas.</b> A classification pipeline after a run: every node green, results cached for the next run.</sub></td>
    <td width="50%"><img alt="Metrics in the inspector" src="docs/assets/metrics.jpg"><br><sub><b>Metrics.</b> Real scores computed by scikit-learn, no mock numbers.</sub></td>
  </tr>
  <tr>
    <td><img alt="Confusion matrix preview" src="docs/assets/plot.jpg"><br><sub><b>Plots.</b> Confusion matrix, ROC, residuals, SHAP and more, downloadable as PNG.</sub></td>
    <td><img alt="Per-node generated code" src="docs/assets/code.jpg"><br><sub><b>Code.</b> The Python each node becomes in the export.</sub></td>
  </tr>
  <tr>
    <td><img alt="Export dialog" src="docs/assets/export.jpg"><br><sub><b>Export.</b> Script, notebook, pipeline JSON, Airflow DAG or Dagster job.</sub></td>
    <td><img alt="Schedules window" src="docs/assets/schedules.jpg"><br><sub><b>Schedules.</b> Run saved pipelines on cron, with a history of every run.</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img alt="Light theme" src="docs/assets/light.jpg"><br><sub><b>Light theme.</b> Both themes are first-class.</sub></td>
  </tr>
</table>

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.11 or newer | Backend runtime |
| **uv** | Latest | Python package manager |
| **Node.js** | 18 or newer | Frontend build toolchain |
| **npm** | 9 or newer | Frontend package manager |

### Install `uv` (Python package manager)

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing so `uv` is on your `PATH`.

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url> athena
cd athena
```

### 2. Install root dev tools

From the project root (installs `concurrently`, which runs both servers together):

```bash
npm install
```

### 3. Install backend dependencies

```bash
cd backend
uv sync
cd ..
```

This creates a `.venv` inside `backend/` and installs all Python dependencies (FastAPI, scikit-learn, pandas, XGBoost, SHAP, matplotlib, etc.).

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running the app

### Start both servers at once (recommended)

From the project root:

```bash
npm run dev
```

This launches:
- **Backend** → `http://localhost:8001` (FastAPI + uvicorn, hot-reload on)
- **Frontend** → `http://localhost:5173` (Vite dev server, HMR on)

Open **`http://localhost:5173`** in your browser.

### Start servers individually

**Backend only:**
```bash
cd backend
uv run uvicorn athena.main:app --reload --port 8001
```

**Frontend only:**
```bash
cd frontend
npm run dev
```

> The frontend proxies `/api` and `/ws` to `localhost:8001` (set `BACKEND_PORT` to use another port), so both must be running for the app to work.

---

## Using the app

1. **Build a pipeline** — drag nodes from the left sidebar onto the canvas, connect output ports to input ports.
2. **Configure nodes** — click any node to open the inspector panel on the right; edit settings in the Settings tab.
3. **Run** — click **Run** (or press `Ctrl/⌘ + Enter`). Nodes light up green as they execute.
4. **Inspect results** — click a completed node and switch to the **Preview**, **Logs**, or **Metrics** tabs. In **Preview**, **Profile** opens a full profile of any table output, and **↓** downloads any output (tables as CSV, models as joblib files).
   The **Code** tab shows the Python that node becomes in the export (with **Full script** for everything); Custom Code and SQL fields are code editors with syntax highlighting. **Tidy layout** (the last button in the canvas controls) arranges the nodes left to right; Ctrl+Z undoes it.
5. **Export code** — click **Export Code** in the top bar to download a standalone Python script, a Jupyter notebook (one cell per node), the pipeline JSON, or an Airflow DAG / Dagster job. The code needs only the libraries it imports, follows your graph exactly, and is tested to produce the same results as running the pipeline in Athena. Plots are saved as PNG files next to the script.
6. **Save / Load** — click **Save** (or `Ctrl/⌘ + S`) and enter a file path; **Load** opens a saved `.athena` file or one from your library.

### Connections (databases)

Click **Connections** in the top bar to save a database connection (PostgreSQL, MySQL/MariaDB, SQLite, DuckDB, SQL Server, or any SQLAlchemy URL), then use the **SQL Query** node to pull data from it.

- **Test connection** checks the settings before you save.
- Passwords are stored in your OS keychain (Windows Credential Manager, macOS Keychain, Secret Service), never in `.athena` files or exported code. You can also enter `env://VAR_NAME` to read a secret from an environment variable.
- Pipelines refer to connections by name, so you can share a pipeline without sharing credentials.
- SQLite works out of the box. Other databases need their driver: `uv pip install -e ".[postgres]"` (or `mysql`, `duckdb`, `mssql`) in `backend/`.

### Files, SQL and cloud storage

- **Parquet Loader** reads a Parquet file or a folder of Parquet files (a partitioned dataset); pick columns to read only what you need.
- **SQL Transform** runs SQL on your data with DuckDB: connected inputs are tables `in1` and `in2`, and you can query files directly (`SELECT * FROM 'data/*.parquet'`). Filter, join, aggregate, window functions.
- **Cloud File Loader** reads CSV, Parquet, JSON Lines or Excel from Amazon S3 (and S3-compatible stores such as MinIO and Cloudflare R2), Google Cloud Storage, Azure Blob / Data Lake, or a local folder. Save the bucket under **Connections → Object Storage** (with **Test connection** and a file browser); paths can be folders or globs like `sales/2026/*.parquet`. Install the driver you need: `uv sync --extra s3` (or `gcs`, `azure`). Exported code reads the same URL with pandas and takes credentials from the environment.

### SaaS apps

Pull data from **GitHub, Stripe, HubSpot, Jira, Zendesk or Shopify** without working out their endpoints and paging (`uv sync --extra api`):

1. **Connections → ＋ GitHub** (or another app): enter just what that app needs (a token; Jira and Zendesk also take your site and email; Shopify your shop name) and **Test connection**. Secrets go to your OS keychain or an `env://VAR` reference.
2. Add a **SaaS Fetch** node, choose the connection, then pick a **Resource** from the list (GitHub issues, Stripe invoices, HubSpot deals, Jira issues…). Some resources take **Parameters**, e.g. `{"owner": "dlt-hub", "repo": "dlt"}` for GitHub issues or `{"jql": "project = ABC"}` for Jira.

Each app's base URL, authentication and pagination are built in. They follow the apps' public API documentation and are tested against local mock servers, not the live services; please report any that don't work with your account. Use **API Fetch** for any other REST API.

### REST APIs

Pull JSON from any REST API with the **API Fetch** node (`uv sync --extra api`, which installs [dlt](https://dlthub.com)).

- Save the API under **Connections → REST API**: base URL, authentication (bearer token, API key in a header or query parameter, or basic auth) and any extra headers. Secrets go to your OS keychain; **Test connection** requests a path you choose.
- In the node, set the endpoint path, query parameters (JSON), and where the records are in the response (e.g. `data.items`, or leave it empty to detect).
- Pagination: *auto* (dlt detects it; check the Logs tab), *page number*, *offset*, *cursor*, *next URL* in the body, or a *Link header*. *Max pages* caps the number of requests (10 by default).
- Nested objects become columns like `address__city`; nested lists are left out and listed in the Logs tab, or keep everything as JSON with *Nested data → json*.
- dlt's anonymous telemetry is switched off, in Athena and in exported scripts.

### Subflows: reusable groups of nodes

Select a few nodes (Ctrl-click them, or Shift-drag a box around them) and press **Ctrl+G** (or the group button in the canvas controls). They become one **subflow** node; the connections that crossed the selection become its inputs and outputs. It runs, caches and exports exactly like the nodes inside it.

Click a subflow to see the nodes inside with their status and previews, rename it, **Ungroup** it to edit (Ctrl+G again to regroup), or **Save to library**. Saved subflows appear under **My subflows** at the top of the node library; drag one into any pipeline.

### Serving: deploy a model

After a run, select a model node (or Pipeline Wrapper, Calibration, Decision Threshold…), open **Preview** and press **Deploy**. Athena packages the trained model as a standalone prediction service in `~/.athena/models/<name>/`:

- `service.py` (FastAPI: `POST /predict`, `GET /schema`, `GET /health`, interactive docs at `/docs`), `model.joblib`, `schema.json` (the features, their kinds and an example request built from medians, never a real row), pinned `requirements.txt`, a `Dockerfile`, a BentoML service with `bentofile.yaml`, and a README. It runs without Athena.
- **Serving** (top bar) lists your packaged models. **Start endpoint** runs one locally (its own process, reachable only from this machine, stopped when Athena stops); the test console sends a request and shows the answer. **Download .zip** to run it elsewhere: `python service.py`, `docker build`, or `bentoml serve`.
- **Build** turns a packaged model into a Docker image (`docker build`) or a Bento (`bentoml build`) with your own Docker / BentoML, in the background: the Serving window follows the build log and, when it's done, shows the command to run it (`docker run --rm -p 8000:8000 <name>:latest`). The first build downloads the base image and the pinned packages.

- **Batch predictions:** the **Batch Predict** node scores a whole table with a packaged model (its preprocessing included) and adds `prediction` and `proba_<class>` columns; follow it with CSV Export and schedule the pipeline for recurring scoring. Outside Athena, the bundle does the same: `python service.py --predict-file new.csv --output predictions.csv` (CSV or Parquet).

**It takes raw rows.** The service replays the pipeline's fitted preprocessing before predicting: Missing Value Imputer, Scaler, One-Hot / Label Encoder, Type Converter, Column Renamer / Selector, Feature Generator, Date Feature Extractor, Text Vectorizer, PCA, String Splitter, Feature Importance Selection and Outlier Detector in clip or flag mode, each with exactly what it learned in training. A **Data Merge** that enriches the data from another table (inner or left join, one row per key on the right) is replayed as a lookup: the service joins each request with that table as it was in training, which is saved in the bundle, so check it's something you're happy to ship. Steps that only shape the training data (removing duplicates or outliers, sampling, SMOTE and other balancing) are skipped. Before packaging, Athena replays the chain on the training rows and checks that it reproduces the model's training features exactly; if it doesn't, or a step can't be replayed (Custom Code, Data Validator, an outer join…), the Serving window names the steps requests must already reflect.

### Quality gates, fairness and model cards

- **Quality Gate** checks acceptance rules against the reports connected to it (Metrics, Fairness Check, drift detection…), one per line:

  ```
  f1 >= 0.9
  roc_auc > 0.85
  drifted_columns == 0
  demographic_parity_difference <= 0.1
  ```

  Connect the model through the gate (its *model* input and output) and put Model Saver, Register Model or anything you deploy after it: when a rule fails the run stops at the gate, so a weak model never reaches them. Set *When a rule fails* to *warn* to only log it.
- **Fairness Check** compares a binary classifier across the groups of a column you choose (region, gender, a one-hot column…): each group's selection rate, true-positive rate and accuracy, plus the demographic parity difference, equal opportunity difference and disparate impact ratio (below 0.8 breaks the common four-fifths rule of thumb). Gate on them like any metric.
- **Model cards:** every deployed bundle includes `MODEL_CARD.md` with the model, its data and preprocessing, the metrics and fairness results from the run, the quality gates it passed (or didn't), and sections for you to complete (intended use, limitations). The Serving window shows the same evidence.

### Monitoring: drift, data quality and live traffic

Install the extra once: `uv sync --extra monitoring` (Evidently).

- **Data Drift Report** compares a *current* table with a *reference* one (usually the training data), column by column, with [Evidently](https://www.evidentlyai.com/): K-S or chi-square by default, or the test you choose (Wasserstein, PSI, Jensen-Shannon…) and its threshold. The report says how many columns drifted (`drifted_columns`, `share_drifted`, `dataset_drift`), and the inspector's **Open report** shows Evidently's full interactive report.
- **Prediction Drift** runs the model on both tables and compares its predictions (and, for a binary classifier, its probabilities): `prediction_drift`, `probability_drift`.
- **Data Quality Report** summarises a table (missing values, duplicated rows, constant or empty columns, per-column statistics), side by side with a reference when one is connected.
- **Gate on them** like any metric: `drifted_columns == 0`, `prediction_drift == 0`, `missing_share <= 0.05` in a Quality Gate. With MLflow tracking on, the HTML reports are logged with the run (`athena/reports/<node>/`).
- **Live traffic:** local endpoints log every predicted row (its raw features, the prediction and a timestamp) to `logs/requests.jsonl` in their bundle and expose **Prometheus metrics** at `/metrics` (requests by status, latency histogram, rows, predictions by class). The **Endpoint Requests** node reads that log as a table: connect it as the *current* input of Data Drift Report or Prediction Drift, with the training data as the reference, to see whether what the model receives still looks like what it learned from. Outside Athena, `python service.py --log-requests requests.jsonl` does the same.

### Schedules: run pipelines automatically

**Schedules** (top bar) runs a saved pipeline file on a cron schedule: pick the file (or one from your library), a preset or a cron expression (`0 2 * * *` is every day at 02:00; the window shows what it means and the next three times), and save. **Run now** starts it immediately, and each schedule keeps the history of its runs: when, why, how long, and which node failed.

- Schedules run while Athena is running, in this computer's local time. Times missed while Athena was closed aren't caught up, and a scheduled run waits if another pipeline is running (it never starts twice). `ATHENA_SCHEDULER=false` keeps them without running them.
- The **saved file** runs, not the canvas: save your changes for the next run to pick them up.
- **Retrain only when the data drifts:** Data Drift Report (new data against the training data) → **Quality Gate** with the rule `dataset_drift == 1` and *When a rule fails* set to **skip**, with the new data passing through the gate into training and Model Saver / Register Model. Without drift the gate skips everything after it and the run still completes; with drift the model is retrained on the new data.
- **Airflow and Dagster:** *Export Airflow DAG* / *Export Dagster job* (in Schedules, or Export Code with a cron) give a zip with a DAG or job that runs each node as its own task (so the orchestrator shows every step and can retry one), on the schedule, plus the standalone script, ready to drop into your orchestrator.

### Comparing versions

**Compare** (top bar) shows what changed on the canvas since a saved pipeline: nodes added, removed or changed (each setting's old → new value, including execution settings and changes inside subflows), connection changes and pipeline settings. **Show on canvas** tags the new and changed nodes until you press **Clear**. Nodes are matched by id, so a node whose settings changed shows as changed, not as removed and re-added.

### Re-running fast: the cache and "Run from here"

- **Unchanged nodes aren't recomputed.** When you run again, every node whose settings, upstream nodes and input files are unchanged reuses its earlier result; it shows a **cached** tag and says so in its Logs tab. Change a node and only it and the nodes after it run again; edit the CSV file and everything that depends on it re-runs.
- Nodes that write files, register models, or read from databases, APIs, cloud storage or custom code always run, since the outside world may have changed. If what they return is unchanged, the nodes after them still come from the cache. Turn **Cache** off in a node's execution settings to make it always run.
- **Run from here** (in the inspector) re-runs the selected node and everything after it, taking the nodes before it from the cache. Hover the button to see which nodes will run.
- The cache is capped by `ATHENA_CACHE_MAX_GB` and cleared when Athena stops, unless `ATHENA_KEEP_CACHE=true`.

### Dataset snapshots

The **Dataset Snapshot** node saves a Parquet copy of the table it receives, named after a hash of its contents (`training-data-3f9c1a....parquet` in `~/.athena/snapshots` or a folder you choose), and passes the table on. The same data always gives the same file, written once; any change gives a new one. Read a snapshot back with the **Parquet Loader** to reproduce a run on exactly the same data.

### Data profiling

After a run, click a node, open **Data Preview** and press **Profile** next to a table output. The profile shows:

- an overview (rows, columns by type, missing cells, duplicate rows, memory) and each column's type, missing share, unique values, distribution and summary;
- **findings**: empty or constant columns, heavy missingness, ID-like columns, high-cardinality categories, strong skew, duplicate rows, a missing or imbalanced target, and columns that look like they leak the target;
- the **target**'s distribution and which columns carry information about it (mutual information). The target is a column named `target` unless you pick another.

Tables over 100,000 rows are profiled on a random sample, and the header says so. Download the table as CSV or Parquet from the same window. Outputs are kept until Athena restarts.

### More models and smarter tuning

- **LightGBM** and **LightGBM Regressor** (included) and **CatBoost** / **CatBoost Regressor** (`uv sync --extra catboost`; handles text columns without one-hot encoding). Connect `X_val`/`y_val` and set *Early stopping rounds* to stop adding trees when validation stops improving.
- **OLS Regression** and **Logistic Regression (statsmodels)** (`uv sync --extra stats`): the classic statistical models with inference. Besides the model, they output a coefficient table (estimate, standard error, t/z statistic, p-value, 95% interval), and the Logs tab shows the full statsmodels summary. Choose *HC3* standard errors when the error variance isn't constant. The models plug into every downstream node (Metrics, Confusion Matrix, Calibration, Decision Threshold, Predict…). Features must be numeric with no missing values.
- **PR-AUC**: the Metrics node now reports average precision next to ROC AUC, and the **Precision-Recall Curve** node plots precision against recall with the no-skill baseline. On imbalanced data it is a more honest score than ROC AUC.
- **HP Tuning Config → Optuna** (`uv sync --extra optuna`): smarter search than grid or random. A value list of more than three numbers (`10-200`) is searched as a range; each trial is cross-validated and shown in the Logs tab.

### Experiment tracking and model registry (MLflow)

Install the extra once: `cd backend && uv sync --extra mlflow`. Then click **Tracking off** in the top bar to turn tracking on for the pipeline.

- Every run is logged to MLflow: each node's settings, metrics, the trained models, the pipeline file and its exported Python script.
- Runs go to Athena's built-in local store (`~/.athena/mlflow`, created on first use in about 20 seconds) or to your own MLflow server: add it under **Connections** as an *MLflow Tracking Server*.
- **Runs** shows the experiment's history. Select two or more runs to compare them side by side: best values in green, settings that differ in amber.
- The **Register Model** node registers a trained model (with an optional alias such as `champion`); **Load Registered Model** brings one back into any pipeline, by alias or version.
- To browse the local store in MLflow's own UI: `uv run mlflow ui --backend-store-uri sqlite:///$HOME/.athena/mlflow/mlflow.db`.

### Forecasting

The **Time Series** nodes work on one series: a date column and a numeric target at a regular frequency (daily, weekly, monthly, hourly...).

- **Time Series Split** sorts by date and holds out the most recent rows. It never shuffles, so the model never sees the future.
- **Forecaster** fits on the training rows and forecasts the test period, or *Horizon* steps past the end when no test set is connected. Methods:
  - *seasonal_naive*: repeats the last season. The baseline every model should beat.
  - *ets*: exponential smoothing (Holt-Winters), with additive or damped trend and additive or multiplicative seasonality.
  - *arima*: seasonal ARIMA with the orders you set.
  - *gbm_lags*: gradient boosting on lagged changes, forecasting step by step.

  It outputs the forecast table (with a prediction interval, except for *gbm_lags*) and, with a test set, MAE, RMSE, MAPE, sMAPE, MASE (below 1 beats the seasonal-naive baseline) and interval coverage. *ets* and *arima* need `uv sync --extra stats`.
- **Backtest** repeats fit-and-forecast over several cut-off dates (rolling origin) and averages the scores: a more reliable estimate than one test window.

The season length comes from the frequency (7 for daily, 12 for monthly, 52 for weekly, 24 for hourly) unless you set it. Repeated dates, missing values and gaps are reported with what to do; forecast several series by filtering to one first.

### Clustering

- **K-Means** (set *Clusters* to 0 to pick k by silhouette), **Hierarchical Clustering** and **DBSCAN** (finds clusters of any shape and marks outliers as -1) add a `cluster` column to the table. Features are the numeric columns, standardised by default so no column dominates by its units. K-Means also outputs a model that assigns new rows to clusters.
- **Cluster Evaluation** reports silhouette (higher is better), Davies-Bouldin (lower is better) and Calinski-Harabasz scores, draws the clusters on their first two principal components, and outputs a profile: each cluster's size and average feature values.

### Calibration and decision thresholds

For classifiers whose probabilities or cut-off matter (risk scores, fraud, churn):

- **Probability Calibration** makes predicted probabilities match how often the class actually occurs (sigmoid, or isotonic for larger data). Check the result with **Calibration Curve** on the test set: a reliability diagram plus the Brier score and expected calibration error.
- **Decision Threshold** picks the probability cut-off for a binary classifier: best F1 or balanced accuracy, the most recall at a minimum precision (or the reverse), or the lowest cost when a missed positive costs more than a false alarm. Its plot shows precision, recall and F1 at every threshold, and the report compares the chosen threshold with the default 0.5.

Both tune on data the model wasn't fitted on: connect `X_val`/`y_val` from **Train/Val/Test Split**, or leave them empty to use k-fold cross-validation on the training set. Never tune on the test set; evaluate on it afterwards.

### AutoML

Install the extra once: `cd backend && uv sync --extra automl` (FLAML with LightGBM and XGBoost; note that it pins XGBoost below 3.0). Then use the **AutoML Search** node, or load the **AutoML Classification** template.

- It tries several model families (LightGBM, XGBoost, random forest, extra trees, linear models, …) and their hyperparameters within a time budget, and outputs the best model, ready for the Metrics, Confusion Matrix and Register Model nodes.
- Task and metric are inferred unless you set them (ROC AUC for binary classification, log loss for multiclass, R² for regression).
- The preview is a leaderboard: each family's best validation score and how many trials it got. Progress streams to the Logs tab.
- Validation scores come from cross-validation on the training data, so they are usually a little optimistic: judge the model by the Metrics node on the test split.
- In a tracked pipeline the leaderboard and the winning configuration are logged to the run.

### Execution settings

Each node's inspector has an **Execution** section: a timeout, retries with backoff, and whether to reuse cached results. Every pipeline runs in a separate worker process, so a crashing or hung node can't take the app down, and **Stop** always works.

**Runs on** picks where a node runs: the local worker (default) or **Ray**. With Ray, the node runs as a Ray task with the CPUs, memory and GPUs you set reserved for it, and joblib work inside it (forests, grid and random search, cross-validation with `n_jobs`) spreads over the cluster.

- **Ray (local cluster)** starts a Ray cluster on this machine for the run (a few seconds), handy to use a GPU or more cores without changing anything else.
- For a remote cluster, add a **Ray cluster** connection (Connections → ＋ Ray cluster) with its address (`ray://head:10001`), then choose it in **Runs on**. Athena can send its own code with each task; the cluster needs the ML libraries the node uses (the connection's *Extra pip packages* can install them).
- Install with `uv pip install 'athena-backend[ray]'`. Results are cached the same way wherever a node ran, logs arrive when a Ray node finishes, and the exported script always runs locally.

**Kubernetes:** add a **Kubernetes cluster** connection and choose it in **Runs on** to run a node as a Kubernetes Job. Install the client with `uv pip install 'athena-backend[k8s]'`.

- **Cluster access** comes from your kubeconfig (a context in it), or the service account when Athena runs inside the cluster. Nothing secret is stored in the connection.
- **Container image:** Python with the libraries your nodes use, plus `fsspec` and your artifact store's driver (e.g. `s3fs`). Athena's own code is sent with each Job unless the image already has `athena-backend`. For example:
  `FROM python:3.11-slim` + `RUN pip install pandas scikit-learn matplotlib pyarrow structlog pydantic pydantic-settings cloudpickle fsspec s3fs` (plus xgboost, lightgbm… if your nodes use them). Matching the library versions you train with locally keeps results identical.
- **Artifact store:** where the node's inputs and outputs are exchanged, e.g. `s3://my-bucket/athena`. Athena reaches it with its usual credentials (or a saved storage connection); pods reach it through cluster identity (a service account) or a Secret loaded as environment variables.
- The node's CPU, memory and GPUs become the pod's requests and limits (`nvidia.com/gpu`), and its timeout becomes the Job's deadline, so the pod stops even if Athena isn't around.
- **Stop** deletes the Job. A wrong image fails the node straight away rather than at the deadline. A pod that crashes is kept for an hour for `kubectl logs`.


### Plugins

Nodes and connectors can come from separately installed Python packages. See [`docs/PLUGINS.md`](docs/PLUGINS.md); `GET /api/plugins` lists what's installed.

### Starter templates

Click **Templates** in the top bar to load a pre-built pipeline. Each template's CSV Loader node points at a small synthetic dataset that ships in `backend/`, so every template runs successfully out of the box with no setup:

| Template | Nodes | Dataset |
|----------|-------|---------|
| Classification Starter | CSV → Imputer → Scaler → Train/Test → Random Forest → Metrics + Confusion Matrix | `backend/data.csv` (300 rows, 4 features + binary `target`) |
| Regression Pipeline | CSV → Imputer → Feature Gen → Train/Test → Linear Regression → Metrics + Residuals | `backend/regression_data.csv` (300 rows, 3 numeric features + continuous `target`) |
| NLP Pipeline | CSV → TF-IDF → Train/Test → Logistic Regression → Metrics + SHAP | `backend/nlp_data.csv` (300 short review-style sentences + binary `target`) |
| AutoML Classification | CSV → Imputer → Train/Test → AutoML Search (30 s) → Metrics + Confusion Matrix | `backend/data.csv` (needs the `automl` extra) |
| Sales Forecasting | CSV → Time Series Split → ETS and a seasonal-naive baseline, plus a 4-fold Backtest | `backend/timeseries_data.csv` (two years of daily `sales`: trend, weekly and yearly seasonality; ETS needs the `stats` extra) |
| Customer Segmentation | CSV → K-Means (k chosen by silhouette) → Cluster Evaluation | `backend/customers_data.csv` (600 customers, 5 numeric features, 4 underlying segments) |

The classification, regression and NLP datasets include a handful of missing values so the Missing Value Imputer node has real work to do, and each is regenerable via the script the datasets were originally produced with (`np.random.default_rng(42)`, so results are reproducible).

---

## Running tests

### Backend

```bash
cd backend
uv run pytest
```

Optional extras (`mlflow`, `automl`, `catboost`, `optuna`, `api`, `stats`, `monitoring`) have their own tests, which are skipped when the extra isn't installed: `uv sync --all-extras` runs everything.

```bash
# Verbose output
uv run pytest -v

# A specific file
uv run pytest tests/test_executor.py -v
```

### Frontend

```bash
cd frontend
npm test
```

---

## Project structure

```
athena/
├── package.json          # root dev scripts (npm run dev, install:all)
│
├── frontend/             # React 18 + TypeScript + Vite
│   └── src/
│       ├── components/   # TopBar, LeftSidebar, GraphCanvas, RightSidebar, modals
│       ├── nodes/        # BaseNode custom React Flow node
│       ├── store/        # Zustand: pipelineStore, executionStore, uiStore
│       ├── hooks/        # useRunPipeline, useAutosave, useTheme, useKeyboardShortcuts
│       ├── lib/          # api client, WebSocket client, DAG utils, validation
│       ├── registry/     # nodeRegistry.ts — single source of truth for node UI metadata
│       └── types/        # TypeScript types mirroring backend Pydantic schemas
│
└── backend/              # FastAPI + Python ML stack
    ├── athena/
    │   ├── api/          # REST routes: /api/pipelines, /api/runs, /api/nodes
    │   ├── core/         # DAG executor, registry, cache, event broker, codegen
    │   ├── nodes/        # ML node handlers (data, quality, feature, model, eval, deploy…)
    │   ├── schemas/      # Pydantic models for pipeline, events, artifacts
    │   ├── storage/      # .athena file save/load, autosave rotation
    │   └── utils/        # DataFrame previews, matplotlib → base64, logging
    └── tests/            # pytest suite
```

---

## Configuration

All backend settings are environment variables prefixed `ATHENA_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ATHENA_HOST` | `127.0.0.1` | Bind address (keep as-is; see security note below) |
| `ATHENA_PORT` | `8000` | Backend port |
| `ATHENA_DATA_DIR` | `~/.athena` | Cache, autosave, and settings root |
| `ATHENA_NODE_TIMEOUT_S` | `300` | Per-node soft timeout in seconds |
| `ATHENA_CACHE_MAX_GB` | `2` | Size limit of the node-result cache; the least recently used results are dropped first |
| `ATHENA_KEEP_CACHE` | `false` | Keep cached node results when Athena restarts (otherwise the cache is cleared on exit) |
| `ATHENA_LOG_LEVEL` | `INFO` | structlog level |
| `ATHENA_ALLOW_CUSTOM_CODE` | `true` | Set to `false` to disable the Custom Code node |
| `ATHENA_SCHEDULER` | `true` | Set to `false` to keep schedules without running them |

Example — raise the node timeout:

```bash
ATHENA_NODE_TIMEOUT_S=600 uv run uvicorn athena.main:app --reload --port 8001
```

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl/⌘ + Enter` | Run pipeline |
| `Ctrl/⌘ + Z` | Undo |
| `Ctrl/⌘ + Shift + Z` | Redo |
| `Ctrl/⌘ + S` | Save pipeline |
| `Delete / Backspace` | Remove selected node or edge |
| `Esc` | Deselect all |

---

## Autosave & recovery

The app autosaves your pipeline to `~/.athena/autosave/latest.athena` every 10 seconds when there are unsaved changes. On next launch, if the autosave differs from the default starter pipeline, Athena automatically restores it and shows a notification.

Up to 5 rotated autosave snapshots are kept (`autosave-1.athena` … `autosave-5.athena`).

---

## Data files

Node file paths (e.g. in the **CSV Loader**) are resolved relative to the directory where you started uvicorn. Use absolute paths to be safe:

```
/Users/you/datasets/iris.csv        # macOS / Linux
C:\Users\you\datasets\iris.csv      # Windows
```

---

## Security note

Athena binds to `127.0.0.1` by default and is intended for **single-user, local use only**. Do not set `ATHENA_HOST=0.0.0.0` unless you understand the implications — the backend exposes your local filesystem and can execute arbitrary Python via the Custom Code node.

---

## Troubleshooting

**"Couldn't reach the backend" toast on Run**
- Make sure `uvicorn` is running on port 8001 (or the port in `BACKEND_PORT`).
- Check the terminal for Python import errors on startup.

**Frontend shows a blank page**
- Open browser devtools console for errors.
- Confirm `npm run dev` is running and the Vite server is on port 5173.

**`uv: command not found`**
- Re-open your terminal after installing uv, or run `source ~/.bashrc` / `source ~/.zshrc`.

**Port 8001 already in use**
```bash
# macOS / Linux
lsof -i :8001 | grep LISTEN
kill -9 <PID>

# Windows PowerShell
netstat -ano | findstr :8001
Stop-Process -Id <PID> -Force
```

**Python version mismatch**
- Athena requires Python 3.11+. Check with `python --version` or `python3 --version`.
- `uv` will automatically use the right version if you have it installed; otherwise install Python 3.11 from [python.org](https://www.python.org/downloads/).
