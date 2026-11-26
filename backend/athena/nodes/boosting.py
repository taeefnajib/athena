"""Gradient boosting libraries as model nodes: LightGBM (base install) and CatBoost (optional extra)."""
from __future__ import annotations

import importlib.util
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.model import _fit_or_tune
from athena.schemas.artifacts import ModelPreview
from athena.sdk import Port, node, ui

MODEL_INPUTS = [Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val"),
                Port("y_val", "y_val"), Port("hp_config", "hpconfig")]
CATBOOST_HINT = "CatBoost isn't installed. Run: pip install 'athena-backend[catboost]' (in backend/: uv sync --extra catboost)"

COMMON_FIELDS = {
    "n_estimators": ui("Trees", min=1),
    "learning_rate": ui("Learning rate", min=0.0001, step=0.01),
    "max_depth": ui("Max depth", help="-1 = no limit (LightGBM)"),
    "early_stopping_rounds": ui("Early stopping rounds", min=0,
                                help="Stop adding trees when the score on the connected X_val/y_val stops improving. 0 = off"),
    "random_state": ui("Random seed"),
}


def _fit(ctx: ExecutionContext, model: Any, early_stopping: int, fit_with_eval: Any) -> tuple[Any, ModelPreview]:
    """Early stopping on the validation inputs when they are connected; otherwise the shared fit/tune path."""
    X_train, y_train = ctx.inputs[0], ctx.inputs[1]
    if X_train is None or y_train is None:
        raise ValueError("Connect X_train and y_train (from a Train/Test Split)")
    X_val = ctx.inputs[2] if len(ctx.inputs) > 2 else None
    y_val = ctx.inputs[3] if len(ctx.inputs) > 3 else None
    if early_stopping and X_val is not None and y_val is not None:
        ctx.logger.info("Fitting with early stopping", model=type(model).__name__, patience=early_stopping, val_rows=len(X_val))
        fit_with_eval(model, X_train, y_train, X_val, y_val, early_stopping)
        best = getattr(model, "best_iteration_", None)
        ctx.logger.info("Fit complete", best_iteration=best if best is not None else "n/a")
        return model, ModelPreview(summary=repr(model))
    if early_stopping:
        ctx.logger.warning("Early stopping needs X_val and y_val connected; training all trees")
    return _fit_or_tune(X_train, y_train, model, ctx)


def _code(cls: str, module: str, params: str) -> str:
    return (
        "# --- Node {id}: " + cls + " ---\n"
        f"from {module} import {cls}\n"
        "_target_col_{var} = 'target' if 'target' in df_train_{src}.columns else df_train_{src}.columns[-1]\n"
        "X_tr_{var} = df_train_{src}.drop(columns=[_target_col_{var}])\n"
        "y_tr_{var} = df_train_{src}[_target_col_{var}]\n"
        "model_{var} = " + cls + "(" + params + ")\n"
        "model_{var}.fit(X_tr_{var}, y_tr_{var})\n"
    )


# ---- LightGBM ------------------------------------------------------------------------------------

class LgbmConfig(BaseModel):
    n_estimators: int = Field(200, ge=1)
    learning_rate: float = Field(0.05, gt=0)
    num_leaves: int = Field(31, ge=2)
    max_depth: int = -1
    min_child_samples: int = Field(20, ge=1)
    subsample: float = Field(1.0, gt=0, le=1)
    colsample_bytree: float = Field(1.0, gt=0, le=1)
    early_stopping_rounds: int = Field(0, ge=0)
    random_state: int = 42


LGBM_FIELDS = {**COMMON_FIELDS, "num_leaves": ui("Leaves per tree", min=2), "min_child_samples": ui("Min samples per leaf", min=1),
               "subsample": ui("Row sample", help="Fraction of rows per tree"), "colsample_bytree": ui("Column sample", help="Fraction of columns per tree")}
LGBM_PARAMS = ("n_estimators={n_estimators}, learning_rate={learning_rate}, num_leaves={num_leaves}, max_depth={max_depth}, "
               "min_child_samples={min_child_samples}, subsample={subsample}, subsample_freq=1, colsample_bytree={colsample_bytree}, "
               "random_state={random_state}, verbose=-1")


def _lgbm(cfg: LgbmConfig, cls: Any) -> Any:
    return cls(n_estimators=cfg.n_estimators, learning_rate=cfg.learning_rate, num_leaves=cfg.num_leaves, max_depth=cfg.max_depth,
               min_child_samples=cfg.min_child_samples, subsample=cfg.subsample, subsample_freq=1 if cfg.subsample < 1 else 0,
               colsample_bytree=cfg.colsample_bytree, random_state=cfg.random_state, verbose=-1)


def _lgbm_eval_fit(model: Any, X: pd.DataFrame, y: pd.Series, Xv: pd.DataFrame, yv: pd.Series, rounds: int) -> None:
    import lightgbm as lgb
    model.fit(X, y, eval_set=[(Xv, yv)], callbacks=[lgb.early_stopping(rounds, verbose=False)])


@node("lgbm", label="LightGBM", category="model", description="Fast gradient boosting with leaf-wise trees (classification)",
      inputs=MODEL_INPUTS, outputs=[Port("model", "model")], fields=LGBM_FIELDS,
      code=_code("LGBMClassifier", "lightgbm", LGBM_PARAMS))
class LgbmClassifierNode:
    Config = LgbmConfig

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from lightgbm import LGBMClassifier
        cfg = self.Config(**ctx.config)
        model, preview = _fit(ctx, _lgbm(cfg, LGBMClassifier), cfg.early_stopping_rounds, _lgbm_eval_fit)
        return HandlerResult(outputs=[model], preview=preview)


@node("lgbm_reg", label="LightGBM Regressor", category="model", description="Fast gradient boosting with leaf-wise trees (regression)",
      inputs=MODEL_INPUTS, outputs=[Port("model", "model")], fields=LGBM_FIELDS,
      code=_code("LGBMRegressor", "lightgbm", LGBM_PARAMS))
class LgbmRegressorNode:
    Config = LgbmConfig

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from lightgbm import LGBMRegressor
        cfg = self.Config(**ctx.config)
        model, preview = _fit(ctx, _lgbm(cfg, LGBMRegressor), cfg.early_stopping_rounds, _lgbm_eval_fit)
        return HandlerResult(outputs=[model], preview=preview)


# ---- CatBoost ------------------------------------------------------------------------------------

class CatBoostConfig(BaseModel):
    n_estimators: int = Field(500, ge=1)
    learning_rate: float = Field(0.05, gt=0)
    max_depth: int = Field(6, ge=1, le=16)
    l2_leaf_reg: float = Field(3.0, ge=0)
    cat_features: str = ""
    early_stopping_rounds: int = Field(0, ge=0)
    random_state: int = 42


CATBOOST_FIELDS = {**COMMON_FIELDS, "max_depth": ui("Depth", min=1, max=16), "l2_leaf_reg": ui("L2 regularization"),
                   "cat_features": ui("Categorical columns", help="Comma-separated. CatBoost encodes them itself, no one-hot needed. "
                                                                  "Empty = text columns are detected automatically")}
CATBOOST_PARAMS = ("iterations={n_estimators}, learning_rate={learning_rate}, depth={max_depth}, l2_leaf_reg={l2_leaf_reg}, "
                   "random_seed={random_state}, verbose=False")


def _code_catboost(cls: str) -> Any:
    def render(v: dict[str, Any]) -> str:
        cats = [c.strip() for c in v["cat_features"].split(",") if c.strip()]
        var = v["var"]
        if cats:
            cat_line = f"_cats_{var} = {cats!r}\n"
        else:
            cat_line = f"_cats_{var} = [c for c in X_tr_{var}.columns if not pd.api.types.is_numeric_dtype(X_tr_{var}[c])]\n"
        base = _code(cls, "catboost", CATBOOST_PARAMS + ", cat_features=_cats_{var} or None").format(**v)
        head, fit = base.rsplit(f"model_{var} = ", 1)
        return "import pandas as pd\n" + head + cat_line + f"model_{var} = " + fit
    return render


def _catboost(cfg: CatBoostConfig, cls_name: str, X: pd.DataFrame | None) -> Any:
    if importlib.util.find_spec("catboost") is None:
        raise RuntimeError(CATBOOST_HINT)
    import catboost
    cats = [c.strip() for c in cfg.cat_features.split(",") if c.strip()]
    if not cats and X is not None:
        cats = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    if X is not None and (missing := [c for c in cats if c not in X.columns]):
        raise ValueError(f"Categorical columns not in the data: {missing}")
    return getattr(catboost, cls_name)(iterations=cfg.n_estimators, learning_rate=cfg.learning_rate, depth=cfg.max_depth,
                                       l2_leaf_reg=cfg.l2_leaf_reg, random_seed=cfg.random_state, verbose=False,
                                       cat_features=cats or None, allow_writing_files=False)


def _catboost_eval_fit(model: Any, X: pd.DataFrame, y: pd.Series, Xv: pd.DataFrame, yv: pd.Series, rounds: int) -> None:
    model.fit(X, y, eval_set=(Xv, yv), early_stopping_rounds=rounds)


@node("catboost", label="CatBoost", category="model",
      description="Gradient boosting that handles categorical columns natively (classification)",
      inputs=MODEL_INPUTS, outputs=[Port("model", "model")], fields=CATBOOST_FIELDS,
      code=_code_catboost("CatBoostClassifier"))
class CatBoostClassifierNode:
    Config = CatBoostConfig

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model, preview = _fit(ctx, _catboost(cfg, "CatBoostClassifier", ctx.inputs[0] if ctx.inputs else None),
                              cfg.early_stopping_rounds, _catboost_eval_fit)
        return HandlerResult(outputs=[model], preview=preview)


@node("catboost_reg", label="CatBoost Regressor", category="model",
      description="Gradient boosting that handles categorical columns natively (regression)",
      inputs=MODEL_INPUTS, outputs=[Port("model", "model")], fields=CATBOOST_FIELDS,
      code=_code_catboost("CatBoostRegressor"))
class CatBoostRegressorNode:
    Config = CatBoostConfig

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model, preview = _fit(ctx, _catboost(cfg, "CatBoostRegressor", ctx.inputs[0] if ctx.inputs else None),
                              cfg.early_stopping_rounds, _catboost_eval_fit)
        return HandlerResult(outputs=[model], preview=preview)
