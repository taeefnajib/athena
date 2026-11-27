"""Export templates: models, tuning, AutoML, custom code and ensembles."""
from __future__ import annotations

from typing import Any, Callable

from athena.nodes.export.common import Template, items, lines

V = dict[str, Any]


def _fit(v: V) -> str:
    """Fit like Athena: through the connected HP Tuning Config's search, or a plain fit."""
    X, y, m = v["in_X_train"], v["in_y_train"], v["out_model"]
    if v.get("in_hp_config", "None") != "None":
        return f"{m} = _athena_tune({m}, {X}, {y}, {v['in_hp_config']})"
    return f"{m}.fit({X}, {y})"


def model(imp: str, ctor: Callable[[V], str]) -> Template:
    def render(v: V) -> str:
        return lines(imp, f"{v['out_model']} = {ctor(v)}", _fit(v))
    return render


def _layers(v: V) -> tuple[int, ...]:
    return tuple(int(x) for x in items(v["layers"]))


def _act(v: V) -> str:
    return "logistic" if v["activation"] == "sigmoid" else v["activation"]


def nb(v: V) -> str:
    cls = v["variant"]
    ctor = f"GaussianNB(var_smoothing={v['var_smoothing']!r})" if cls == "GaussianNB" else f"{cls}()"
    return lines(f"from sklearn.naive_bayes import {cls}", f"{v['out_model']} = {ctor}", _fit(v))


# ---- boosting libraries (early stopping on X_val/y_val, as in Athena) ------------------------------

def _early(v: V) -> bool:
    return bool(v["early_stopping_rounds"]) and v["in_X_val"] != "None" and v["in_y_val"] != "None"


def lgbm(cls: str) -> Template:
    def render(v: V) -> str:
        m, X, y = v["out_model"], v["in_X_train"], v["in_y_train"]
        ctor = (f"{cls}(n_estimators={v['n_estimators']}, learning_rate={v['learning_rate']}, num_leaves={v['num_leaves']}, "
                f"max_depth={v['max_depth']}, min_child_samples={v['min_child_samples']}, subsample={v['subsample']}, "
                f"subsample_freq={1 if float(v['subsample']) < 1 else 0}, colsample_bytree={v['colsample_bytree']}, "
                f"random_state={v['random_state']}, verbose=-1)")
        if _early(v):
            fit = (f"{m}.fit({X}, {y}, eval_set=[({v['in_X_val']}, {v['in_y_val']})], "
                   f"callbacks=[lgb.early_stopping({v['early_stopping_rounds']}, verbose=False)])")
            return lines("import lightgbm as lgb", f"from lightgbm import {cls}", f"{m} = {ctor}", fit)
        return lines(f"from lightgbm import {cls}", f"{m} = {ctor}", _fit(v))
    return render


def catboost(cls: str) -> Template:
    def render(v: V) -> str:
        m, X, y = v["out_model"], v["in_X_train"], v["in_y_train"]
        cats = items(v["cat_features"])
        cat_expr = repr(cats) if cats else f"[c for c in {X}.columns if not pd.api.types.is_numeric_dtype({X}[c])]"
        ctor = (f"{cls}(iterations={v['n_estimators']}, learning_rate={v['learning_rate']}, depth={v['max_depth']}, "
                f"l2_leaf_reg={v['l2_leaf_reg']}, random_seed={v['random_state']}, verbose=False, "
                f"cat_features=_cats or None, allow_writing_files=False)")
        fit = (f"{m}.fit({X}, {y}, eval_set=({v['in_X_val']}, {v['in_y_val']}), early_stopping_rounds={v['early_stopping_rounds']})"
               if _early(v) else _fit(v))
        return lines("import pandas as pd", f"from catboost import {cls}", f"_cats = {cat_expr}", f"{m} = {ctor}", fit)
    return render


# ---- AutoML (FLAML) --------------------------------------------------------------------------------

def automl(v: V) -> str:
    m, X, y = v["out_model"], v["in_X_train"], v["in_y_train"]
    task = (repr(v["task"]) if v["task"] != "auto" else
            "('classification' if pd.api.types.is_bool_dtype(_y) or not pd.api.types.is_numeric_dtype(_y)\n"
            "         or (np.allclose(_y.dropna(), _y.dropna().round()) and _y.nunique() <= max(20, int(0.05 * len(_y.dropna()))))\n"
            "         else 'regression')")
    metric = v["metric"]
    metric_expr = (
        "('r2' if _task == 'regression' else ('roc_auc' if _y.nunique() == 2 else 'log_loss'))" if metric == "auto"
        else f"{{'f1': 'macro_f1', 'roc_auc': 'roc_auc_ovr'}}.get({metric!r}, {metric!r}) if _task == 'classification' and _y.nunique() > 2 else {metric!r}"
    )
    extra = []
    if items(v["estimators"]):
        extra.append(f"estimator_list={items(v['estimators'])!r}")
    if v["n_trials"]:
        extra.append(f"max_iter={int(v['n_trials'])}")
    if v["in_X_val"] != "None" and v["in_y_val"] != "None":
        extra.append(f"X_val={v['in_X_val']}, y_val={v['in_y_val']}, eval_method='holdout'")
    elif v["eval_method"] != "auto":
        extra.append(f"eval_method={v['eval_method']!r}")
    extra_s = (", " + ", ".join(extra)) if extra else ""
    return lines(
        "import numpy as np", "import pandas as pd", "from flaml import AutoML",
        f"_y = pd.Series({y})", f"_task = {task}", f"_metric = {metric_expr}",
        f"{m} = AutoML()",
        f"{m}.fit({X}, {y}, task=_task, metric=_metric, time_budget={int(v['time_budget'])}, seed={int(v['random_state'])}, "
        f"mlflow_logging=False{extra_s})",
        f"print('Best model:', {m}.best_estimator, {m}.best_config)",
        f"{v['out_report']} = {{'best_estimator': {m}.best_estimator, 'best_config': {m}.best_config, 'best_loss': {m}.best_loss}}",
    )


# ---- advanced --------------------------------------------------------------------------------------

def hp_tune(v: V) -> str:
    from athena.nodes.advanced import _parse_values
    grid = {str(r.get("key", "")).strip(): _parse_values(str(r.get("values", "")).strip())
            for r in v["params"] if str(r.get("key", "")).strip() and str(r.get("values", "")).strip()}
    hp = {"method": v["method"], "scoring": v["scoring"], "n_iter": v["n_iter"], "cv": v["cv"], "n_jobs": v["n_jobs"], "param_grid": grid}
    return lines(f"{v['out_hp_config']} = {hp!r}")


def custom_code(v: V) -> str:
    fn = f"_custom_{v['var']}"
    body = "\n".join(f"    {ln}" for ln in str(v["code"]).splitlines()) or "    return df"
    return lines("import numpy as np", "import pandas as pd", f"def {fn}(df, pd, np):", body,
                 f"{v['out_dataset']} = {fn}({v['in_dataset']}.copy(), pd, np)")


def pipeline_wrap(v: V) -> str:
    memory = "'pipeline_cache'" if v["memory"] else "None"
    return lines("from sklearn.pipeline import Pipeline", f"{v['out_pipeline']} = Pipeline(steps=[('model', {v['in_model']})], memory={memory})")


# ---- ensembles (Athena's wrappers for already-fitted models are copied into the script) ------------

def _models(v: V) -> list[str]:
    return [v[f"in_model_{i}"] for i in range(1, 6) if v.get(f"in_model_{i}", "None") != "None"]


def voting(v: V) -> str:
    weights = [float(w) for w in items(v["weights"])] or None
    return lines(f"{v['out_model']} = _VotingEnsemble([{', '.join(_models(v))}], voting={v['voting']!r}, weights={weights!r})")


def stacking(v: V) -> str:
    meta = "LogisticRegression(max_iter=200)" if v["meta"] == "LogisticRegression" else "LinearRegression()"
    return lines(f"from sklearn.linear_model import {v['meta']}",
                 f"{v['out_model']} = _StackingEnsemble([{', '.join(_models(v))}], {meta}).fit({v['in_X_train']}, {v['in_y_train']})")


EXPORT: dict[str, Template] = {
    "lin_reg": model("from sklearn.linear_model import LinearRegression", lambda v: f"LinearRegression(fit_intercept={bool(v['fit_intercept'])})"),
    "log_reg": model("from sklearn.linear_model import LogisticRegression", lambda v: f"LogisticRegression(C={v['C']}, solver={v['solver']!r}, max_iter={v['max_iter']})"),
    "dtree": model("from sklearn.tree import DecisionTreeClassifier", lambda v: f"DecisionTreeClassifier(max_depth={v['max_depth']}, min_samples_split={v['min_samples_split']}, criterion={v['criterion']!r}, random_state=42)"),
    "rf": model("from sklearn.ensemble import RandomForestClassifier", lambda v: f"RandomForestClassifier(n_estimators={v['n_estimators']}, max_depth={v['max_depth']}, max_features={v['max_features']!r}, random_state={v['random_state']})"),
    "xgb": model("from xgboost import XGBClassifier", lambda v: f"XGBClassifier(n_estimators={v['n_estimators']}, learning_rate={v['learning_rate']}, max_depth={v['max_depth']}, subsample={v['subsample']}, eval_metric='logloss', verbosity=0)"),
    "svm": model("from sklearn.svm import SVC", lambda v: f"SVC(C={v['C']}, kernel={v['kernel']!r}, gamma={v['gamma']!r}, probability=True, random_state=42)"),
    "knn": model("from sklearn.neighbors import KNeighborsClassifier", lambda v: f"KNeighborsClassifier(n_neighbors={v['n_neighbors']}, metric={v['metric']!r}, weights={v['weights']!r})"),
    "nb": nb,
    "mlp": model("from sklearn.neural_network import MLPClassifier", lambda v: f"MLPClassifier(hidden_layer_sizes={_layers(v)!r}, activation={_act(v)!r}, learning_rate_init={v['lr']}, max_iter={v['epochs']}, batch_size={v['batch_size']}, random_state=42)"),
    "ridge": model("from sklearn.linear_model import Ridge", lambda v: f"Ridge(alpha={v['alpha']}, fit_intercept={bool(v['fit_intercept'])})"),
    "lasso": model("from sklearn.linear_model import Lasso", lambda v: f"Lasso(alpha={v['alpha']}, max_iter={v['max_iter']})"),
    "rf_reg": model("from sklearn.ensemble import RandomForestRegressor", lambda v: f"RandomForestRegressor(n_estimators={v['n_estimators']}, max_depth={v['max_depth']}, max_features={v['max_features']!r}, random_state={v['random_state']})"),
    "xgb_reg": model("from xgboost import XGBRegressor", lambda v: f"XGBRegressor(n_estimators={v['n_estimators']}, learning_rate={v['learning_rate']}, max_depth={v['max_depth']}, subsample={v['subsample']}, verbosity=0)"),
    "dtree_reg": model("from sklearn.tree import DecisionTreeRegressor", lambda v: f"DecisionTreeRegressor(max_depth={v['max_depth']}, min_samples_split={v['min_samples_split']}, criterion={v['criterion']!r}, random_state=42)"),
    "svr": model("from sklearn.svm import SVR", lambda v: f"SVR(C={v['C']}, kernel={v['kernel']!r}, epsilon={v['epsilon']}, gamma={v['gamma']!r})"),
    "knn_reg": model("from sklearn.neighbors import KNeighborsRegressor", lambda v: f"KNeighborsRegressor(n_neighbors={v['n_neighbors']}, metric={v['metric']!r}, weights={v['weights']!r})"),
    "mlp_reg": model("from sklearn.neural_network import MLPRegressor", lambda v: f"MLPRegressor(hidden_layer_sizes={_layers(v)!r}, activation={_act(v)!r}, learning_rate_init={v['lr']}, max_iter={v['epochs']}, batch_size={v['batch_size']}, random_state=42)"),
    "gb_reg": model("from sklearn.ensemble import GradientBoostingRegressor", lambda v: f"GradientBoostingRegressor(n_estimators={v['n_estimators']}, learning_rate={v['learning_rate']}, max_depth={v['max_depth']}, subsample={v['subsample']}, random_state={v['random_state']})"),
    "lgbm": lgbm("LGBMClassifier"), "lgbm_reg": lgbm("LGBMRegressor"),
    "catboost": catboost("CatBoostClassifier"), "catboost_reg": catboost("CatBoostRegressor"),
    "automl": automl, "hp_tune": hp_tune, "custom_code": custom_code, "pipeline_wrap": pipeline_wrap,
    "voting": voting, "stacking": stacking,
}
