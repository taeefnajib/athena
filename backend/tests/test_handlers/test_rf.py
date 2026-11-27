import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from athena.nodes.model import RfHandler, LinRegHandler, LogRegHandler
from athena.nodes.eval import MetricsHandler, ConfMatrixHandler, ResidualHandler
from athena.nodes.split import TrainTestHandler
from athena.core.handler import ExecutionContext
import structlog


def _ctx(tmp_path: Path, node_type: str, config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(
        node_id="n1",
        node_type=node_type,
        config=config,
        inputs=inputs,
        run_id="test-run",
        cache_dir=tmp_path,
        logger=structlog.get_logger(),
    )


def _clf_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(200, 4))
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    df = pd.DataFrame(X, columns=["f0", "f1", "f2", "f3"])
    df["target"] = y
    return df


def _reg_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(200, 3))
    y = X[:, 0] * 2 + X[:, 1] + rng.normal(scale=0.1, size=200)
    df = pd.DataFrame(X, columns=["f0", "f1", "f2"])
    df["target"] = y
    return df


class Split:
    """Outputs of the train_test node, in port order: X_train, y_train, X_test, y_test."""

    def __init__(self, outputs: list) -> None:
        self.X_train, self.y_train, self.X_test, self.y_test = outputs

    @property
    def train(self) -> list:  # model inputs: X_train, y_train, X_val, y_val, hp_config
        return [self.X_train, self.y_train, None, None, None]

    def test(self, model: object) -> list:  # eval inputs: model, X_test, y_test
        return [model, self.X_test, self.y_test]


def _split(df: pd.DataFrame, tmp_path: Path) -> Split:
    ctx = _ctx(tmp_path, "train_test", {"test_size": 0.2, "random_state": 42, "stratify": False}, [df])
    return Split(TrainTestHandler()(ctx).outputs)


def test_rf_fits_and_predicts(tmp_path: Path):
    df = _clf_df()
    sp = _split(df, tmp_path)
    handler = RfHandler()
    ctx = _ctx(tmp_path, "rf", {"n_estimators": 10, "max_depth": 5, "max_features": "sqrt", "random_state": 42}, sp.train)
    result = handler(ctx)
    model = result.outputs[0]
    assert hasattr(model, "predict")
    assert result.preview.kind == "model"


def test_rf_metrics(tmp_path: Path):
    df = _clf_df()
    sp = _split(df, tmp_path)

    rf_ctx = _ctx(tmp_path, "rf", {"n_estimators": 10, "max_depth": 5, "max_features": "sqrt", "random_state": 42}, sp.train)
    model = RfHandler()(rf_ctx).outputs[0]

    met_ctx = _ctx(tmp_path, "metrics", {"task": "classification", "average": "weighted"}, sp.test(model))
    result = MetricsHandler()(met_ctx)
    m = result.metrics
    assert "accuracy" in m
    assert "f1" in m
    assert 0.0 <= m["accuracy"] <= 1.0


def test_lin_reg_fits(tmp_path: Path):
    df = _reg_df()
    sp = _split(df, tmp_path)
    handler = LinRegHandler()
    ctx = _ctx(tmp_path, "lin_reg", {"fit_intercept": True}, sp.train)
    result = handler(ctx)
    model = result.outputs[0]
    assert hasattr(model, "coef_")


def test_log_reg_fits(tmp_path: Path):
    df = _clf_df()
    sp = _split(df, tmp_path)
    handler = LogRegHandler()
    ctx = _ctx(tmp_path, "log_reg", {"C": 1.0, "solver": "lbfgs", "max_iter": 200}, sp.train)
    result = handler(ctx)
    model = result.outputs[0]
    assert hasattr(model, "predict")


def test_conf_matrix_produces_plot(tmp_path: Path):
    df = _clf_df()
    sp = _split(df, tmp_path)
    rf_ctx = _ctx(tmp_path, "rf", {"n_estimators": 10, "max_depth": 5, "max_features": "sqrt", "random_state": 42}, sp.train)
    model = RfHandler()(rf_ctx).outputs[0]

    cm_ctx = _ctx(tmp_path, "conf_matrix", {"normalize": "none", "cmap": "Blues"}, sp.test(model))
    result = ConfMatrixHandler()(cm_ctx)
    assert result.preview.kind == "plot"
    assert len(result.preview.data) > 100  # non-empty base64


def test_residual_plot(tmp_path: Path):
    df = _reg_df()
    sp = _split(df, tmp_path)
    lr_ctx = _ctx(tmp_path, "lin_reg", {"fit_intercept": True}, sp.train)
    model = LinRegHandler()(lr_ctx).outputs[0]

    res_ctx = _ctx(tmp_path, "residual", {}, sp.test(model))
    result = ResidualHandler()(res_ctx)
    assert result.preview.kind == "plot"


def test_regression_metrics(tmp_path: Path):
    df = _reg_df()
    sp = _split(df, tmp_path)
    lr_ctx = _ctx(tmp_path, "lin_reg", {"fit_intercept": True}, sp.train)
    model = LinRegHandler()(lr_ctx).outputs[0]

    met_ctx = _ctx(tmp_path, "metrics", {"task": "regression", "average": "weighted"}, sp.test(model))
    result = MetricsHandler()(met_ctx)
    assert "rmse" in result.metrics
    assert "r2" in result.metrics
    assert result.metrics["rmse"] >= 0
