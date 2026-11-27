"""Probability calibration, calibration curves and decision-threshold tuning."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import GaussianNB

from athena.core.handler import ExecutionContext
from athena.nodes.calibration import (
    CalibrateHandler,
    CalibrationCurveHandler,
    ThresholdTuneHandler,
    _athena_threshold,
    _athena_tuning_scores,
)


def _ctx(config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="c1", node_type="t", config=config, inputs=inputs, run_id="r",
                            cache_dir=Path("."), logger=structlog.get_logger())


@pytest.fixture(scope="module")
def data():
    """Imbalanced binary data (about 15% positives) split into train / validation / test."""
    X, y = make_classification(n_samples=3000, n_features=8, n_informative=4, weights=[0.85], flip_y=0.03, random_state=0)
    X = pd.DataFrame(X, columns=[f"f{i}" for i in range(8)])
    y = pd.Series(y, name="target")
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, stratify=y, random_state=0)
    X_tr, X_va, y_tr, y_va = train_test_split(X_tr, y_tr, test_size=0.3, stratify=y_tr, random_state=0)
    return X_tr, y_tr, X_va, y_va, X_te, y_te


def test_calibration_improves_a_miscalibrated_model(data):
    X_tr, y_tr, X_va, y_va, X_te, y_te = (_dup(d) for d in data)
    nb = GaussianNB().fit(X_tr, y_tr)  # naive Bayes double-counts duplicated evidence: over-confident
    before = brier_score_loss(y_te, nb.predict_proba(X_te)[:, 1])
    for inputs in ([nb, X_tr, y_tr, X_va, y_va], [nb, X_tr, y_tr]):  # validation set, then cross-validation
        res = CalibrateHandler()(_ctx({"method": "sigmoid"}, inputs))
        after = brier_score_loss(y_te, res.outputs[0].predict_proba(X_te)[:, 1])
        assert after < before * 0.9, (before, after)
    assert "validation set" in CalibrateHandler()(_ctx({}, [nb, X_tr, y_tr, X_va, y_va])).preview.summary
    assert "5-fold cross-validation" in CalibrateHandler()(_ctx({}, [nb, X_tr, y_tr])).preview.summary


def _dup(d):
    """Feature frames repeated three times side by side (targets pass through)."""
    return pd.concat([d.add_suffix(f"_{k}") for k in range(3)], axis=1) if isinstance(d, pd.DataFrame) else d


def test_calibration_with_a_validation_set_keeps_the_fitted_model(data):
    X_tr, y_tr, X_va, y_va, _X_te, _ = data
    rf = RandomForestClassifier(n_estimators=30, random_state=0).fit(X_tr, y_tr)
    cal = CalibrateHandler()(_ctx({"method": "isotonic"}, [rf, X_tr, y_tr, X_va, y_va])).outputs[0]
    assert cal.calibrated_classifiers_[0].estimator.estimator is rf  # frozen, not refitted


def test_calibration_needs_probabilities(data):
    X_tr, y_tr, *_ = data
    with pytest.raises(ValueError, match="doesn't output probabilities"):
        CalibrateHandler()(_ctx({}, [LinearRegression().fit(X_tr, y_tr), X_tr, y_tr]))


def test_calibration_curve_reports_brier_and_ece(data):
    X_tr, y_tr, X_va, y_va, X_te, y_te = (_dup(d) for d in data)
    nb = GaussianNB().fit(X_tr, y_tr)
    raw = CalibrationCurveHandler()(_ctx({}, [nb, X_te, y_te]))
    cal = CalibrateHandler()(_ctx({}, [nb, X_tr, y_tr, X_va, y_va])).outputs[0]
    fixed = CalibrationCurveHandler()(_ctx({"strategy": "quantile"}, [cal, X_te, y_te]))
    assert raw.preview.kind == "plot" and raw.metrics["brier"] == pytest.approx(brier_score_loss(y_te, nb.predict_proba(X_te)[:, 1]))
    assert fixed.metrics["ece"] < raw.metrics["ece"]
    assert 0 <= fixed.metrics["ece"] <= 1


def test_threshold_search_matches_brute_force():
    rng = np.random.default_rng(3)
    is_pos = rng.random(500) < 0.2
    scores = np.clip(is_pos * 0.35 + rng.random(500) * 0.65, 0, 1)
    t, table = _athena_threshold(scores, is_pos, "f1")
    best = max(table["threshold"], key=lambda c: _f1(scores >= c, is_pos))
    assert _f1(scores >= t, is_pos) == pytest.approx(_f1(scores >= best, is_pos))
    i = int(np.argmin(np.abs(table["threshold"] - t)))
    assert table["f1"][i] == pytest.approx(_f1(scores >= t, is_pos))


def _f1(pred: np.ndarray, pos: np.ndarray) -> float:
    tp = (pred & pos).sum(); fp = (pred & ~pos).sum(); fn = (~pred & pos).sum()
    return 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)


def test_threshold_objectives(data):
    X_tr, y_tr, X_va, y_va, _, _ = data
    lr = LogisticRegression(max_iter=500).fit(X_tr, y_tr)
    run = lambda cfg: ThresholdTuneHandler()(_ctx(cfg, [lr, X_tr, y_tr, X_va, y_va]))
    cheap_fn = run({"objective": "min_cost", "cost_fp": 1, "cost_fn": 1}).outputs[1]["threshold"]
    costly_fn = run({"objective": "min_cost", "cost_fp": 1, "cost_fn": 20}).outputs[1]["threshold"]
    assert costly_fn < cheap_fn  # expensive misses push the threshold down
    rep = run({"objective": "max_recall_at_precision", "constraint": 0.8}).outputs[1]
    assert rep["precision"] >= 0.8
    rep = run({"objective": "max_precision_at_recall", "constraint": 0.9}).outputs[1]
    assert rep["recall"] >= 0.9
    rep = run({"objective": "f1"}).outputs[1]
    assert rep["f1"] >= rep["f1_at_0.5"]  # on imbalanced data, 0.5 is rarely the best cut-off
    # the top-scored row is a negative, so precision never exceeds 0.5
    with pytest.raises(ValueError, match="No threshold reaches precision 0.6"):
        _athena_threshold([0.9, 0.8, 0.7, 0.6], [False, True, False, True], "max_recall_at_precision", 0.6)
    t, _table = _athena_threshold([0.9, 0.8, 0.7, 0.6], [False, True, False, True], "max_recall_at_precision", 0.5)
    assert t <= 0.6  # every row positive: precision 0.5 and recall 1.0 beats recall 0.5 at the same precision
    assert 0.2 < t  # all thresholds up to 0.6 tie; it takes the middle of that range, not the edge


def test_tuned_model_predicts_with_the_threshold(data):
    X_tr, y_tr, X_va, y_va, X_te, _ = data
    lr = LogisticRegression(max_iter=500).fit(X_tr, y_tr)
    model, rep = ThresholdTuneHandler()(_ctx({"objective": "min_cost", "cost_fn": 10}, [lr, X_tr, y_tr, X_va, y_va])).outputs
    expected = (lr.predict_proba(X_te)[:, 1] >= rep["threshold"]).astype(int)
    assert (model.predict(X_te) == expected).all()
    assert np.allclose(model.predict_proba(X_te), lr.predict_proba(X_te))  # probabilities are unchanged


def test_threshold_without_validation_uses_out_of_fold_scores(data):
    X_tr, y_tr, *_ = data
    rf = RandomForestClassifier(n_estimators=30, random_state=0).fit(X_tr, y_tr)
    scores, is_pos, _ = _athena_tuning_scores(rf, X_tr, y_tr, cv=4)
    in_sample = rf.predict_proba(X_tr)[:, 1]
    # a forest is near-certain about its own training rows; out-of-fold scores are honest
    assert brier_score_loss(is_pos, scores) > 2 * brier_score_loss(y_tr == 1, in_sample)


def test_string_labels_positive_class_and_errors(data):
    X_tr, y_tr, X_va, y_va, X_te, _y_te = data
    names = {0: "stay", 1: "churn"}
    ys = y_tr.map(names)
    lr = LogisticRegression(max_iter=500).fit(X_tr, ys)
    model, _rep = ThresholdTuneHandler()(_ctx({"positive_class": "churn"}, [lr, X_tr, ys, X_va, y_va.map(names)])).outputs
    assert set(model.predict(X_te)) <= {"stay", "churn"}
    # "stay" sorts after "churn", so the default positive class would be "stay"; naming it flips the scores
    _, _flip, pos = _athena_tuning_scores(lr, X_tr, ys, X_va, y_va.map(names))
    assert pos == "stay"
    with pytest.raises(ValueError, match="isn't one of the classes"):
        ThresholdTuneHandler()(_ctx({"positive_class": "nope"}, [lr, X_tr, ys, X_va, y_va.map(names)]))
    X3, y3 = make_classification(n_samples=300, n_classes=3, n_informative=4, random_state=0)
    multi = LogisticRegression(max_iter=500).fit(X3, y3)
    with pytest.raises(ValueError, match="binary target"):
        ThresholdTuneHandler()(_ctx({}, [multi, X3, y3]))
