"""LightGBM and CatBoost model nodes: fitting, early stopping, categorical columns, export."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog

from athena.core.codegen import pipeline_to_python
from athena.core.handler import ExecutionContext
from athena.nodes.boosting import CatBoostClassifierNode, CatBoostRegressorNode, LgbmClassifierNode, LgbmRegressorNode
from athena.schemas.pipeline import PipelineSpec


def _ctx(config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="m1", node_type="t", config=config, inputs=inputs, run_id="r",
                            cache_dir=Path("."), logger=structlog.get_logger())


def _data(n: int = 400, categorical: bool = False):
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.normal(size=(n, 3)), columns=["a", "b", "c"])
    if categorical:
        X["city"] = rng.choice(["dhaka", "berlin", "lima"], size=n)
        y_clf = ((X["a"] > 0) | (X["city"] == "dhaka")).astype(int)
    else:
        y_clf = (X["a"] + X["b"] > 0).astype(int)
    y_reg = X["a"] * 2 + X["b"]
    return X.iloc[:300], X.iloc[300:], y_clf.iloc[:300], y_clf.iloc[300:], y_reg.iloc[:300], y_reg.iloc[300:]


def test_lightgbm_classifier_and_regressor():
    Xtr, Xte, ytr, yte, rtr, rte = _data()
    clf = LgbmClassifierNode()(_ctx({"n_estimators": 100}, [Xtr, ytr, None, None, None])).outputs[0]
    assert (clf.predict(Xte) == yte).mean() > 0.85
    reg = LgbmRegressorNode()(_ctx({}, [Xtr, rtr, None, None, None])).outputs[0]
    assert np.corrcoef(reg.predict(Xte), rte)[0, 1] > 0.9


def test_lightgbm_early_stopping_uses_validation_inputs():
    Xtr, Xte, ytr, yte, *_ = _data()
    model = LgbmClassifierNode()(_ctx({"n_estimators": 2000, "learning_rate": 0.3, "early_stopping_rounds": 10},
                                      [Xtr, ytr, Xte, yte, None])).outputs[0]
    assert 0 < model.best_iteration_ < 2000


def test_catboost_handles_text_columns_natively():
    pytest.importorskip("catboost")
    Xtr, Xte, ytr, yte, rtr, rte = _data(categorical=True)
    clf = CatBoostClassifierNode()(_ctx({"n_estimators": 200}, [Xtr, ytr, None, None, None])).outputs[0]
    assert (clf.predict(Xte) == yte).mean() > 0.85
    reg = CatBoostRegressorNode()(_ctx({"n_estimators": 200, "early_stopping_rounds": 20}, [Xtr, rtr, Xte, rte, None])).outputs[0]
    assert np.corrcoef(reg.predict(Xte), rte)[0, 1] > 0.9


def test_catboost_rejects_unknown_categorical_columns():
    pytest.importorskip("catboost")
    Xtr, _, ytr, *_ = _data()
    with pytest.raises(ValueError, match="not in the data"):
        CatBoostClassifierNode()(_ctx({"cat_features": "nope"}, [Xtr, ytr, None, None, None]))


@pytest.mark.parametrize(("node_type", "needle"), [
    ("lgbm", "LGBMClassifier(n_estimators=200, learning_rate=0.05"),
    ("catboost_reg", "CatBoostRegressor(iterations=500"),
])
def test_boosting_export(node_type: str, needle: str):
    spec = PipelineSpec.model_validate({"nodes": [
        {"id": "s", "type": "train_test", "position": {"x": 0, "y": 0}, "config": {}},
        {"id": "m", "type": node_type, "position": {"x": 1, "y": 0}, "config": {}},
    ], "edges": [{"id": "e", "source": "s", "target": "m"}, {"id": "e2", "source": "s", "target": "m", "source_port": 1, "target_port": 1}]})
    code = pipeline_to_python(spec)
    assert needle in code and "model_m.fit(X_train_s, y_train_s)" in code
    if node_type.startswith("catboost"):
        assert "cat_features=_cats or None" in code and "_cats = [c for c in X_train_s.columns" in code
