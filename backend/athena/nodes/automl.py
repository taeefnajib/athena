"""AutoML Search (FLAML): try several model families and their hyperparameters within a time budget.

Optional extra: ``pip install 'athena-backend[automl]'`` (FLAML with LightGBM and XGBoost).
The output model is FLAML's fitted ``AutoML`` object: it predicts like any scikit-learn model
(``predict``, ``predict_proba``) and applies the same preprocessing FLAML used while searching.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import re
from collections import Counter
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe

INSTALL_HINT = "AutoML needs FLAML. Run: pip install 'athena-backend[automl]' (in backend/: uv sync --extra automl)"
MINIMIZE = {"rmse", "mae", "mse", "log_loss"}
CLASSIFICATION_METRICS = {"accuracy", "f1", "roc_auc", "log_loss"}
REGRESSION_METRICS = {"r2", "rmse", "mae", "mse"}
MAX_LOG_LINES = 400


def infer_task(y: pd.Series) -> str:
    """Classification for labels (strings, booleans, or few distinct integers), otherwise regression."""
    if pd.api.types.is_bool_dtype(y) or not pd.api.types.is_numeric_dtype(y):  # strings, categories, booleans
        return "classification"
    values = y.dropna()
    if np.allclose(values, values.round()) and values.nunique() <= max(20, int(0.05 * len(values))):
        return "classification"
    return "regression"


def resolve_metric(metric: str, task: str, n_classes: int) -> str:
    """Athena's metric choice -> FLAML's metric name (explicit, so scores can be reported correctly)."""
    if metric == "auto":
        return "r2" if task == "regression" else ("roc_auc" if n_classes == 2 else "log_loss")
    if task == "regression" and metric in CLASSIFICATION_METRICS:
        raise ValueError(f"{metric} is a classification metric, but the target looks continuous (regression). Set Task or Metric.")
    if task == "classification" and metric in REGRESSION_METRICS:
        raise ValueError(f"{metric} is a regression metric, but the task is classification. Set Task or Metric.")
    if n_classes > 2:
        return {"f1": "macro_f1", "roc_auc": "roc_auc_ovr"}.get(metric, metric)
    return metric


def _score(loss: float, metric: str) -> float:
    """FLAML minimises a loss: 1 - score for metrics where higher is better."""
    return loss if metric in MINIMIZE else 1 - loss


class _LogBridge(logging.Handler):
    """Forward FLAML's progress messages to the node's Logs tab (skipping the per-iteration noise)."""

    def __init__(self, ctx: ExecutionContext) -> None:
        super().__init__(logging.INFO)
        self.ctx, self.sent = ctx, 0
        self.learners: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage().strip()
        m = re.match(r"iteration \d+, current learner (\w+)", msg)
        if m:
            self.learners[m.group(1)] += 1
            return
        if msg and self.sent < MAX_LOG_LINES:
            self.sent += 1
            self.ctx.logger.info(msg.replace("\t", " "))


def _code_automl(v: dict[str, Any]) -> str:
    est = [e.strip() for e in v["estimators"].split(",") if e.strip()]
    est_arg = f", estimator_list={est!r}" if est else ""
    iters = f", max_iter={int(v['n_trials'])}" if v["n_trials"] else ""
    task = (f"{v['task']!r}" if v["task"] != "auto"
            else f"'classification' if y_tr_{v['var']}.nunique() <= 20 else 'regression'  # Athena inferred the task")
    return (
        f"# --- Node {v['id']}: AutoML Search (FLAML) ---\n"
        "from flaml import AutoML\n"
        f"_target_col_{v['var']} = 'target' if 'target' in df_train_{v['src']}.columns else df_train_{v['src']}.columns[-1]\n"
        f"X_tr_{v['var']} = df_train_{v['src']}.drop(columns=[_target_col_{v['var']}])\n"
        f"y_tr_{v['var']} = df_train_{v['src']}[_target_col_{v['var']}]\n"
        f"_task_{v['var']} = {task}\n"
        f"model_{v['var']} = AutoML()\n"
        f"model_{v['var']}.fit(X_tr_{v['var']}, y_tr_{v['var']}, task=_task_{v['var']}, metric={v['metric']!r}, "
        f"time_budget={int(v['time_budget'])}, eval_method={v['eval_method']!r}, seed={int(v['random_state'])}{est_arg}{iters})\n"
        f"print('Best model:', model_{v['var']}.best_estimator, model_{v['var']}.best_config)\n"
    )


@node(
    "automl", label="AutoML Search", category="advanced",
    description="Try several model families and hyperparameters within a time budget (FLAML) and keep the best",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val"), Port("y_val", "y_val")],
    outputs=[Port("model", "model"), Port("report", "report")],
    fields={
        "task": ui("Task", help="auto: classification for labels or few distinct integers, otherwise regression"),
        "metric": ui("Optimize", help="auto: ROC AUC (binary), log loss (multiclass), R² (regression)"),
        "time_budget": ui("Time budget (s)", min=1, help="Keep it below the node's timeout (Execution section, default 300 s)"),
        "n_trials": ui("Max trials", min=0, help="0 = as many as fit in the time budget"),
        "estimators": ui("Model families", help="Comma-separated, empty = all available. e.g. lgbm, rf, xgboost, extra_tree, lrl1, kneighbor"),
        "eval_method": ui("Validation", help="auto: cross-validation for small data, holdout for large. A connected X_val/y_val is used as the holdout."),
        "random_state": ui("Random seed"),
    },
    code=_code_automl,
)
class AutoMLHandler:
    class Config(BaseModel):
        task: Literal["auto", "classification", "regression"] = "auto"
        metric: Literal["auto", "accuracy", "f1", "roc_auc", "log_loss", "r2", "rmse", "mae", "mse"] = "auto"
        time_budget: int = Field(60, ge=1, le=86_400)
        n_trials: int = Field(0, ge=0)
        estimators: str = ""
        eval_method: Literal["auto", "holdout", "cv"] = "auto"
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        if importlib.util.find_spec("flaml") is None:
            raise RuntimeError(INSTALL_HINT)
        import os
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        from flaml import AutoML
        from flaml.automl.logger import logger as flaml_logger

        cfg = self.Config(**ctx.config)
        X_train, y_train = (ctx.inputs + [None] * 4)[:2]
        X_val, y_val = (ctx.inputs + [None] * 4)[2:4]
        if X_train is None or y_train is None:
            raise ValueError("Connect X_train and y_train (from a Train/Test Split)")
        task = cfg.task if cfg.task != "auto" else infer_task(pd.Series(y_train))
        n_classes = int(pd.Series(y_train).nunique()) if task == "classification" else 0
        metric = resolve_metric(cfg.metric, task, n_classes)
        estimators = [e.strip() for e in cfg.estimators.split(",") if e.strip()]
        ctx.logger.info("AutoML search", task=task, metric=metric, time_budget_s=cfg.time_budget,
                        families=", ".join(estimators) or "all available")

        settings: dict[str, Any] = dict(task=task, metric=metric, time_budget=cfg.time_budget, seed=cfg.random_state,
                                        mlflow_logging=False, verbose=3, log_file_name=str(ctx.cache_dir / f"{ctx.node_id}_flaml.log"))
        if estimators:
            settings["estimator_list"] = estimators
        if cfg.n_trials:
            settings["max_iter"] = cfg.n_trials
        if X_val is not None and y_val is not None:
            settings.update(X_val=X_val, y_val=y_val, eval_method="holdout")
        elif cfg.eval_method != "auto":
            settings["eval_method"] = cfg.eval_method

        bridge = _LogBridge(ctx)
        flaml_logger.addHandler(bridge)
        automl = AutoML()
        try:
            automl.fit(X_train, y_train, **settings)
        except Exception as exc:
            raise ValueError(f"AutoML search failed: {str(exc).splitlines()[0]}") from exc
        finally:
            flaml_logger.removeHandler(bridge)
        if automl.best_estimator is None:
            raise ValueError("No model finished within the time budget. Increase the budget or choose faster model families.")

        board = _leaderboard(automl, metric, bridge.learners)
        best = _score(automl.best_loss, metric)
        trials = int(sum(bridge.learners.values()))
        ctx.logger.info("Best model", family=automl.best_estimator, **{metric: round(best, 4)}, trials=trials)
        ctx.logger.info("Best configuration", config=board.loc[board["winner"], "best_config"].iloc[0])
        _log_to_tracking(ctx, board, automl, metric)
        return HandlerResult(
            outputs=[automl, board],
            # The inspector is narrow: preview without the long config column (it stays in the report output).
            preview=preview_dataframe(board.drop(columns=["best_config"])),
            metrics={f"best_{metric}": float(best), "trials": float(trials),
                     "time_to_best_s": float(automl.time_to_find_best_model or 0)},
        )


def _leaderboard(automl: Any, metric: str, trials: Counter[str]) -> pd.DataFrame:
    rows = []
    for family, loss in automl.best_loss_per_estimator.items():
        finished = loss is not None and np.isfinite(loss)
        rows.append({
            "model_family": family,
            f"best_{metric}": round(_score(loss, metric), 4) if finished else None,
            "trials": trials.get(family, 0),
            "best_config": json.dumps({k: (round(v, 4) if isinstance(v, float) else v)
                                       for k, v in (automl.best_config_per_estimator.get(family) or {}).items()}, default=str),
            "winner": family == automl.best_estimator,
        })
    board = pd.DataFrame(rows)
    return board.sort_values(f"best_{metric}", ascending=metric in MINIMIZE, na_position="last").reset_index(drop=True)


def _log_to_tracking(ctx: ExecutionContext, board: pd.DataFrame, automl: Any, metric: str) -> None:
    """If the pipeline is tracked, attach the leaderboard and the winning configuration to the run."""
    try:
        from athena.tracking import observer
        if observer.CURRENT is None:
            return
        import mlflow
        if mlflow.active_run() is None:
            return
        mlflow.log_table(board, f"athena/{ctx.node_id}_automl_leaderboard.json")
        mlflow.log_params({f"{ctx.node_id}.best.family": automl.best_estimator,
                           **{f"{ctx.node_id}.best.{k}": str(v)[:500] for k, v in (automl.best_config or {}).items()}})
    except Exception as exc:  # tracking extras must never fail the node
        ctx.logger.warning(f"Couldn't log the AutoML leaderboard to the tracked run: {exc}")
