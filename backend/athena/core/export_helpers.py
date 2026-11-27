"""Small helper functions that exported scripts may need. Each is written into the script only when a
template uses it, so exports stay self-contained (no Athena import) and as short as possible."""
from __future__ import annotations

import inspect

ATHENA_TARGET = '''\
def _athena_target(df, explicit=""):
    """The target column: the one you named, else 'target', else the last column."""
    if explicit.strip():
        return explicit.strip()
    return "target" if "target" in df.columns else df.columns[-1]
'''

ATHENA_TUNE = '''\
def _athena_tune(model, X, y, hp):
    """Hyperparameter search configured by an HP Tuning Config node; returns the best fitted model."""
    from sklearn.base import clone
    from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, cross_val_score
    grid, method = hp["param_grid"], hp["method"]
    if not grid:
        return model.fit(X, y)
    if method == "Optuna":
        import optuna

        def space(values):
            numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
            if numeric and len(values) > 3:
                lo, hi = min(values), max(values)
                if all(isinstance(v, int) for v in values):
                    return "int", (int(lo), int(hi))
                return "float", (float(lo), float(hi), lo > 0 and hi / lo >= 100)
            return "categorical", list(values)

        spaces = {k: space(v) for k, v in grid.items()}

        def objective(trial):
            params = {}
            for name, (kind, spec) in spaces.items():
                if kind == "int":
                    params[name] = trial.suggest_int(name, *spec)
                elif kind == "float":
                    params[name] = trial.suggest_float(name, spec[0], spec[1], log=spec[2])
                else:
                    params[name] = trial.suggest_categorical(name, spec)
            return cross_val_score(clone(model).set_params(**params), X, y, cv=hp["cv"],
                                   scoring=hp["scoring"], n_jobs=hp["n_jobs"]).mean()

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=hp["n_iter"])
        return clone(model).set_params(**study.best_params).fit(X, y)
    if method == "Grid":
        search = GridSearchCV(model, grid, cv=hp["cv"], n_jobs=hp["n_jobs"], scoring=hp["scoring"])
    else:  # Random (and Bayesian, which Athena runs as a random search when scikit-optimize is missing)
        search = RandomizedSearchCV(model, grid, n_iter=min(hp["n_iter"], 50), cv=hp["cv"],
                                    n_jobs=hp["n_jobs"], scoring=hp["scoring"], random_state=42)
    search.fit(X, y)
    print("Best CV score:", search.best_score_, "params:", search.best_params_)
    return search.best_estimator_
'''


def _class_source(dotted: str) -> str:
    module, name = dotted.rsplit(".", 1)
    import importlib
    src = inspect.getsource(getattr(importlib.import_module(module), name))
    return src if src.endswith("\n") else src + "\n"


# name -> source (or a callable producing it, for classes copied verbatim from Athena)
HELPERS: dict[str, object] = {
    "_athena_target": ATHENA_TARGET,
    "_athena_tune": ATHENA_TUNE,
    "_VotingEnsemble": lambda: _class_source("athena.nodes.ensemble._VotingEnsemble"),
    "_StackingEnsemble": lambda: _class_source("athena.nodes.ensemble._StackingEnsemble"),
    "_athena_tuning_scores": lambda: _class_source("athena.nodes.calibration._athena_tuning_scores"),
    "_athena_threshold": lambda: _class_source("athena.nodes.calibration._athena_threshold"),
    **{name: (lambda n=name: _class_source(f"athena.nodes.forecast_core.{n}")) for name in (
        "_athena_date_col", "_athena_series", "_athena_season", "_athena_forecast", "_athena_forecast_metrics", "_athena_forecast_table",
        "_athena_backtest_table", "_athena_ts_split")},
    **{name: (lambda n=name: _class_source(f"athena.nodes.cluster.{n}")) for name in (
        "_athena_cluster_matrix", "_athena_silhouette", "_athena_auto_k", "_athena_cluster_profile", "_athena_cluster_report")},
    "_athena_snapshot": lambda: _class_source("athena.nodes.snapshot._athena_snapshot"),
    "_StatsBase": lambda: _class_source("athena.nodes.stats._StatsBase"),
    "_StatsOLS": lambda: _class_source("athena.nodes.stats._StatsOLS"),
    "_StatsLogit": lambda: _class_source("athena.nodes.stats._StatsLogit"),
}
# helpers another helper needs (a subclass needs its base class, defined above it in HELPERS)
HELPER_DEPS: dict[str, list[str]] = {
    "_StatsOLS": ["_StatsBase"], "_StatsLogit": ["_StatsBase"],
    "_athena_series": ["_athena_date_col"], "_athena_ts_split": ["_athena_date_col"],
    "_athena_forecast_table": ["_athena_series", "_athena_season", "_athena_forecast", "_athena_forecast_metrics"],
    "_athena_backtest_table": ["_athena_series", "_athena_season", "_athena_forecast", "_athena_forecast_metrics"],
    "_athena_auto_k": ["_athena_silhouette"], "_athena_cluster_report": ["_athena_silhouette"],
}
HELPER_IMPORTS = {"_StatsBase": ["from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin"],
                  "_VotingEnsemble": ["import numpy as np", "import pandas as pd"],
                  "_StackingEnsemble": ["import numpy as np", "import pandas as pd"]}


def helpers_for(code: str) -> tuple[list[str], list[str]]:
    """(helper sources, extra imports) needed by ``code``."""
    sources, imports = [], []
    used = {name for name in HELPERS if f"{name}(" in code}
    while True:  # dependencies of dependencies too
        more = {dep for name in used for dep in HELPER_DEPS.get(name, [])} - used
        if not more:
            break
        used |= more
    for name, src in HELPERS.items():  # HELPERS order keeps base classes before subclasses
        if name in used:
            sources.append(src() if callable(src) else src)  # type: ignore[operator]
            imports += HELPER_IMPORTS.get(name, [])
    return sources, imports
