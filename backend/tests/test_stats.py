"""statsmodels OLS / Logit nodes, the Precision-Recall Curve node and PR-AUC in Metrics."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
import structlog
from sklearn.datasets import make_classification
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import average_precision_score

from athena.core.handler import ExecutionContext
from athena.nodes.calibration import PrCurveHandler, ThresholdTuneHandler
from athena.nodes.eval import MetricsHandler
from athena.nodes.stats import StatsLogitHandler, StatsOlsHandler


def _ctx(config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="s1", node_type="t", config=config, inputs=inputs, run_id="r",
                            cache_dir=Path("."), logger=structlog.get_logger())


@pytest.fixture(scope="module")
def reg():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"x1": rng.normal(size=300), "x2": rng.normal(size=300), "noise": rng.normal(size=300)})
    y = pd.Series(3 + 2 * X["x1"] - 1.5 * X["x2"] + rng.normal(0, 1 + np.abs(X["x1"]), 300), name="y")  # heteroskedastic
    return X, y


@pytest.fixture(scope="module")
def clf():
    X, y = make_classification(n_samples=800, n_features=5, n_informative=3, n_redundant=0, weights=[0.8], random_state=1)
    return pd.DataFrame(X, columns=[f"f{i}" for i in range(5)]), pd.Series(y, name="target")


def test_ols_matches_statsmodels_and_sklearn(reg):
    X, y = reg
    res = StatsOlsHandler()(_ctx({}, [X, y]))
    model, table = res.outputs
    direct = sm.OLS(y, sm.add_constant(X)).fit()
    assert np.allclose(table["coef"], direct.params.values) and np.allclose(table["p_value"], direct.pvalues.values)
    assert np.allclose(model.coef_, LinearRegression().fit(X, y).coef_)
    assert np.allclose(model.predict(X), direct.predict(sm.add_constant(X)))
    assert list(table.columns) == ["term", "coef", "std_err", "statistic", "p_value", "ci_low", "ci_high"]
    p = dict(zip(table["term"], table["p_value"]))
    assert p["x1"] < 1e-6 and p["x2"] < 1e-6 and p["noise"] > 0.05
    assert res.metrics["r2"] == pytest.approx(direct.rsquared) and res.preview.kind == "dataframe"


def test_robust_errors_change_uncertainty_not_estimates(reg):
    X, y = reg
    plain = StatsOlsHandler()(_ctx({}, [X, y])).outputs[1]
    hc3 = StatsOlsHandler()(_ctx({"cov_type": "HC3"}, [X, y])).outputs[1]
    assert np.allclose(plain["coef"], hc3["coef"])
    assert hc3.loc[hc3["term"] == "x1", "std_err"].item() > plain.loc[plain["term"] == "x1", "std_err"].item()
    no_const = StatsOlsHandler()(_ctx({"add_constant": False}, [X, y])).outputs[1]
    assert "const" not in set(no_const["term"])


def test_logit_matches_unpenalised_sklearn_and_works_downstream(clf):
    X, y = clf
    model, _table = StatsLogitHandler()(_ctx({}, [X, y])).outputs
    sk = LogisticRegression(penalty=None, max_iter=2000).fit(X, y)
    assert np.allclose(model.coef_, sk.coef_, atol=1e-3)
    direct = sm.Logit(y, sm.add_constant(X)).fit(disp=0)
    assert np.allclose(model.predict_proba(X)[:, 1], direct.predict(sm.add_constant(X)))  # exact vs statsmodels
    assert np.allclose(model.predict_proba(X), sk.predict_proba(X), atol=1e-3)  # sklearn's solver tolerance
    assert (model.predict(X) == sk.predict(X)).mean() > 0.995
    report = MetricsHandler()(_ctx({}, [model, X, y])).outputs[0]
    assert {"accuracy", "roc_auc", "pr_auc"} <= set(report)
    _tuned, rep = ThresholdTuneHandler()(_ctx({}, [model, X, y])).outputs
    assert 0 < rep["threshold"] < 1


def test_logit_string_labels_and_errors(clf):
    X, y = clf
    ys = y.map({0: "no", 1: "yes"})
    model = StatsLogitHandler()(_ctx({}, [X, ys])).outputs[0]
    assert list(model.classes_) == ["no", "yes"] and set(model.predict(X)) <= {"no", "yes"}
    with pytest.raises(ValueError, match="binary target"):
        StatsLogitHandler()(_ctx({}, [X, pd.Series(np.arange(len(X)) % 3)]))
    with pytest.raises(ValueError, match="numeric features"):
        StatsOlsHandler()(_ctx({}, [X.assign(city="dhaka"), y]))
    with pytest.raises(ValueError, match="missing values"):
        StatsOlsHandler()(_ctx({}, [X.assign(f0=np.where(np.arange(len(X)) < 5, np.nan, X["f0"])), y]))


def test_logit_reports_non_convergence(clf):
    X, y = clf
    separated = X.assign(leak=y * 10.0)  # perfectly separates the classes
    res = StatsLogitHandler()(_ctx({"max_iter": 10}, [separated, y]))
    assert res.metrics["converged"] == 0.0 or res.outputs[0].warnings_


def test_missing_statsmodels_gives_an_install_hint(monkeypatch, reg):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "statsmodels" else real(name, *a))
    with pytest.raises(RuntimeError, match="uv sync --extra stats"):
        StatsOlsHandler()(_ctx({}, list(reg)))


def test_pr_curve_and_metrics_pr_auc(clf):
    X, y = clf
    lr = LogisticRegression(max_iter=1000).fit(X, y)
    expected = average_precision_score(y, lr.predict_proba(X)[:, 1])
    res = PrCurveHandler()(_ctx({}, [lr, X, y]))
    assert res.metrics["pr_auc"] == pytest.approx(expected) and res.preview.kind == "plot"
    assert MetricsHandler()(_ctx({}, [lr, X, y])).metrics["pr_auc"] == pytest.approx(expected)
    flipped = PrCurveHandler()(_ctx({"positive_class": "0"}, [lr, X, y])).metrics["pr_auc"]
    assert flipped == pytest.approx(average_precision_score(y == 0, lr.predict_proba(X)[:, 0]))


def test_pr_curve_multiclass_and_limits():
    X, y = make_classification(n_samples=600, n_classes=3, n_informative=4, random_state=0)
    lr = LogisticRegression(max_iter=1000).fit(X, y)
    res = PrCurveHandler()(_ctx({}, [lr, X, y]))
    assert {"ap_0", "ap_1", "ap_2"} <= set(res.metrics)
    assert res.metrics["pr_auc"] == pytest.approx(np.mean([res.metrics[f"ap_{c}"] for c in range(3)]))
    assert MetricsHandler()(_ctx({}, [lr, X, y])).metrics["pr_auc"] == pytest.approx(res.metrics["pr_auc"])
    X9, y9 = make_classification(n_samples=900, n_classes=9, n_informative=6, n_clusters_per_class=1, random_state=0)
    with pytest.raises(ValueError, match="Too many classes"):
        PrCurveHandler()(_ctx({}, [LogisticRegression(max_iter=300).fit(X9, y9), X9, y9]))
