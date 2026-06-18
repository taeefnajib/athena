import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from athena.nodes.quality import ImputerHandler, DupRemoverHandler
from athena.core.handler import ExecutionContext
import structlog


def _ctx(tmp_path: Path, config: dict, df: pd.DataFrame) -> ExecutionContext:
    return ExecutionContext(
        node_id="n1",
        node_type="imputer",
        config=config,
        inputs=[df],
        run_id="test-run",
        cache_dir=tmp_path,
        logger=structlog.get_logger(),
    )


def _df_with_nans() -> pd.DataFrame:
    return pd.DataFrame({
        "a": [1.0, np.nan, 3.0, 4.0],
        "b": [np.nan, 2.0, np.nan, 4.0],
        "c": ["x", "y", "z", "w"],
    })


def test_imputer_mean(tmp_path: Path):
    df = _df_with_nans()
    handler = ImputerHandler()
    ctx = _ctx(tmp_path, {"strategy": "mean", "fill_value": "0", "cols": ""}, df)
    result = handler(ctx)
    out = result.outputs[0]
    assert out["a"].isna().sum() == 0
    assert out["b"].isna().sum() == 0
    assert pytest.approx(out["a"].iloc[1], abs=1e-6) == (1 + 3 + 4) / 3


def test_imputer_median(tmp_path: Path):
    df = _df_with_nans()
    handler = ImputerHandler()
    ctx = _ctx(tmp_path, {"strategy": "median", "fill_value": "0", "cols": ""}, df)
    result = handler(ctx)
    out = result.outputs[0]
    assert out["a"].isna().sum() == 0


def test_imputer_constant(tmp_path: Path):
    df = _df_with_nans()
    handler = ImputerHandler()
    ctx = _ctx(tmp_path, {"strategy": "constant", "fill_value": "-1", "cols": ""}, df)
    result = handler(ctx)
    out = result.outputs[0]
    assert out["a"].iloc[1] == -1.0
    assert out["b"].iloc[0] == -1.0


def test_imputer_specific_cols(tmp_path: Path):
    df = _df_with_nans()
    handler = ImputerHandler()
    ctx = _ctx(tmp_path, {"strategy": "mean", "fill_value": "0", "cols": "a"}, df)
    result = handler(ctx)
    out = result.outputs[0]
    assert out["a"].isna().sum() == 0
    assert out["b"].isna().sum() > 0  # b not imputed


def test_imputer_metrics_tracks_filled(tmp_path: Path):
    df = _df_with_nans()
    handler = ImputerHandler()
    ctx = _ctx(tmp_path, {"strategy": "mean", "fill_value": "0", "cols": ""}, df)
    result = handler(ctx)
    assert result.metrics["missing_filled"] == 3.0


def test_dup_remover(tmp_path: Path):
    df = pd.DataFrame({"a": [1, 1, 2, 3], "b": [4, 4, 5, 6]})
    handler = DupRemoverHandler()
    ctx = ExecutionContext(
        node_id="n2", node_type="dup_remover", config={"subset": "", "keep": "first"},
        inputs=[df], run_id="r", cache_dir=tmp_path, logger=structlog.get_logger(),
    )
    result = handler(ctx)
    assert len(result.outputs[0]) == 3
    assert result.metrics["removed"] == 1.0
