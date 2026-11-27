"""statsmodels regression with inference: OLS and Logit (optional extra ``athena-backend[stats]``).

The models are wrapped as scikit-learn-style estimators so every downstream node (Metrics, Confusion Matrix,
Calibration, Decision Threshold, Predict, Model Saver, ...) works with them unchanged. Each node also outputs
the coefficient table (estimate, standard error, statistic, p-value, 95% interval) as a dataset.
"""
from __future__ import annotations

import importlib.util
from typing import Any, Literal

from pydantic import BaseModel, Field
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe

INSTALL_HINT = "statsmodels isn't installed. Install it with: uv sync --extra stats (or pip install statsmodels)"


# ---- estimators (copied verbatim into exported scripts: keep them self-contained) ----------------------

class _StatsBase(BaseEstimator):
    """Shared plumbing for the statsmodels wrappers: design matrix, summary, coefficient table."""

    def _design(self, X):
        import pandas as pd
        import statsmodels.api as sm
        X = pd.DataFrame(X).copy()
        X.columns = [str(c) for c in X.columns]
        bad = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c]) and not pd.api.types.is_bool_dtype(X[c])]
        if bad:
            raise ValueError(f"statsmodels needs numeric features; encode {bad[:5]} first (One-Hot or Label Encoder)")
        if X.isna().any().any():
            raise ValueError(f"Features contain missing values ({X.columns[X.isna().any()].tolist()[:5]}); impute them first")
        X = X.astype(float)
        return sm.add_constant(X, has_constant="add") if self.add_constant else X

    def summary(self):
        return str(self.results_.summary())

    def coef_table(self):
        import pandas as pd
        r = self.results_
        ci = r.conf_int(0.05)
        return pd.DataFrame({"term": list(r.params.index), "coef": r.params.values, "std_err": r.bse.values,
                             "statistic": r.tvalues.values, "p_value": r.pvalues.values,
                             "ci_low": ci.iloc[:, 0].values, "ci_high": ci.iloc[:, 1].values})


class _StatsOLS(RegressorMixin, _StatsBase):
    """Ordinary least squares (statsmodels) with a scikit-learn interface and the full statistical summary."""

    def __init__(self, add_constant=True, cov_type="nonrobust"):
        self.add_constant = add_constant
        self.cov_type = cov_type

    def fit(self, X, y):
        import numpy as np
        import statsmodels.api as sm
        Xd = self._design(X)
        self.feature_names_in_ = np.array([c for c in Xd.columns if c != "const"])
        self.results_ = sm.OLS(np.asarray(y, dtype=float), Xd).fit(cov_type=self.cov_type)
        params = self.results_.params
        self.intercept_ = float(params["const"]) if "const" in params else 0.0
        self.coef_ = np.asarray(params.drop("const", errors="ignore"), dtype=float)
        return self

    def predict(self, X):
        import numpy as np
        return np.asarray(self.results_.predict(self._design(X)), dtype=float)


class _StatsLogit(ClassifierMixin, _StatsBase):
    """Binary logistic regression (statsmodels Logit) with a scikit-learn interface and the full summary."""

    def __init__(self, add_constant=True, cov_type="nonrobust", max_iter=100):
        self.add_constant = add_constant
        self.cov_type = cov_type
        self.max_iter = max_iter

    def fit(self, X, y):
        import warnings

        import numpy as np
        import statsmodels.api as sm
        Xd = self._design(X)
        y = np.asarray(y)
        self.classes_ = np.unique(y)
        if len(self.classes_) != 2:
            raise ValueError(f"Logit needs a binary target; this one has {len(self.classes_)} classes")
        self.feature_names_in_ = np.array([c for c in Xd.columns if c != "const"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.results_ = sm.Logit((y == self.classes_[1]).astype(float), Xd).fit(
                disp=0, maxiter=int(self.max_iter), cov_type=self.cov_type)
        self.warnings_ = sorted({str(w.message).split("\n")[0] for w in caught})
        self.converged_ = bool(self.results_.mle_retvals.get("converged", True))
        params = self.results_.params
        self.intercept_ = np.array([float(params["const"])]) if "const" in params else np.zeros(1)
        self.coef_ = np.asarray(params.drop("const", errors="ignore"), dtype=float).reshape(1, -1)
        return self

    def predict_proba(self, X):
        import numpy as np
        p = np.asarray(self.results_.predict(self._design(X)), dtype=float)
        return np.column_stack([1 - p, p])

    def predict(self, X):
        return self.classes_[(self.predict_proba(X)[:, 1] >= 0.5).astype(int)]


# ---- nodes ---------------------------------------------------------------------------------------------

COV = Literal["nonrobust", "HC3", "HC1"]
FIELDS = {
    "add_constant": ui("Add intercept"),
    "cov_type": ui("Standard errors", help="nonrobust assumes constant error variance; HC3 / HC1 are heteroskedasticity-robust."),
}


def _require() -> None:
    if importlib.util.find_spec("statsmodels") is None:
        raise RuntimeError(INSTALL_HINT)


def _result(ctx: ExecutionContext, model: Any, metrics: dict[str, float]) -> HandlerResult:
    table = model.coef_table()
    for line in model.summary().splitlines():
        ctx.logger.info(line)
    significant = table[(table["term"] != "const") & (table["p_value"] < 0.05)]["term"].tolist()
    ctx.logger.info(f"Significant at 5%: {', '.join(significant) or 'none'}")
    return HandlerResult(outputs=[model, table], preview=preview_dataframe(table.round(6)), metrics=metrics)


@node(
    "sm_ols", label="OLS Regression (statsmodels)", category="model",
    description="Linear regression with coefficients, standard errors, p-values and confidence intervals",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train")],
    outputs=[Port("model", "model"), Port("coefficients", "dataset")],
    fields=FIELDS, code=EXPORT["sm_ols"],
)
class StatsOlsHandler:
    class Config(BaseModel):
        add_constant: bool = True
        cov_type: COV = "nonrobust"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        _require()
        cfg = self.Config(**ctx.config)
        X, y = ctx.inputs[0], ctx.inputs[1]
        model = _StatsOLS(cfg.add_constant, cfg.cov_type).fit(X, y)
        r = model.results_
        return _result(ctx, model, {"r2": float(r.rsquared), "adj_r2": float(r.rsquared_adj), "aic": float(r.aic),
                                    "bic": float(r.bic), "f_pvalue": float(r.f_pvalue), "n": float(r.nobs)})


@node(
    "sm_logit", label="Logistic Regression (statsmodels)", category="model",
    description="Binary logistic regression with coefficients, standard errors, p-values and confidence intervals",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train")],
    outputs=[Port("model", "model"), Port("coefficients", "dataset")],
    fields={**FIELDS, "max_iter": ui("Max iterations")}, code=EXPORT["sm_logit"],
)
class StatsLogitHandler:
    class Config(BaseModel):
        add_constant: bool = True
        cov_type: COV = "nonrobust"
        max_iter: int = Field(100, ge=10, le=10_000)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        _require()
        cfg = self.Config(**ctx.config)
        X, y = ctx.inputs[0], ctx.inputs[1]
        model = _StatsLogit(cfg.add_constant, cfg.cov_type, cfg.max_iter).fit(X, y)
        for w in model.warnings_:
            ctx.logger.warning(w)
        if not model.converged_:
            ctx.logger.warning(f"Didn't converge in {cfg.max_iter} iterations: raise Max iterations, scale the features, "
                               "or check for a feature that perfectly separates the classes")
        r = model.results_
        return _result(ctx, model, {"pseudo_r2": float(r.prsquared), "aic": float(r.aic), "bic": float(r.bic),
                                    "llr_pvalue": float(r.llr_pvalue), "n": float(r.nobs), "converged": float(model.converged_)})

