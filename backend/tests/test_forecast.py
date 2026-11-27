"""Time-series nodes: series parsing, chronological split, forecasters, metrics, backtests."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog

from athena.core.handler import ExecutionContext
from athena.nodes.forecast import BacktestHandler, ForecasterHandler
from athena.nodes.forecast_core import (
    _athena_forecast,
    _athena_forecast_metrics,
    _athena_season,
    _athena_series,
    _athena_ts_split,
)

BACKEND = Path(__file__).parents[1]


def _ctx(config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="f1", node_type="t", config=config, inputs=inputs, run_id="r",
                            cache_dir=Path("."), logger=structlog.get_logger())


def _frame(values, start="2025-01-01", freq="D", name="sales") -> pd.DataFrame:
    return pd.DataFrame({"date": pd.date_range(start, periods=len(values), freq=freq).strftime("%Y-%m-%d"), name: values})


@pytest.fixture(scope="module")
def sales() -> pd.DataFrame:
    return pd.read_csv(BACKEND / "timeseries_data.csv")


def test_series_parsing_and_errors():
    df = _frame(np.arange(30.0)).sample(frac=1, random_state=0)  # shuffled rows
    dates, y, dc, tc, freq = _athena_series(df)
    assert (dc, tc, freq) == ("date", "sales", "D") and dates.is_monotonic_increasing and y[0] == 0
    with pytest.raises(ValueError, match="repeated dates"):
        _athena_series(pd.concat([df, df.head(2)]))
    with pytest.raises(ValueError, match="missing values"):
        _athena_series(df.assign(sales=df["sales"].where(df["sales"] != 5)))
    with pytest.raises(ValueError, match="evenly spaced"):
        _athena_series(df.drop(index=df.index[3]))
    with pytest.raises(ValueError, match="set Target"):
        _athena_series(df.assign(other=1.0))
    assert _athena_series(df.assign(other=1.0), target="other")[3] == "other"
    with pytest.raises(ValueError, match="No date column"):
        _athena_series(pd.DataFrame({"a": [1.0, 2.0, 3.0]}))


def test_season_from_frequency():
    assert [_athena_season(f) for f in ("D", "MS", "ME", "W-SUN", "QS-OCT", "h", "YS-JAN")] == [7, 12, 12, 52, 4, 24, 1]
    assert _athena_season("D", 30) == 30


def test_split_is_chronological(sales):
    train, test = _athena_ts_split(sales.sample(frac=1, random_state=1), test_periods=28)
    assert len(test) == 28 and train["date"].max() < test["date"].min() and test["date"].is_monotonic_increasing
    _train2, test2 = _athena_ts_split(sales, test_fraction=0.25)
    assert len(test2) == round(len(sales) * 0.25)
    with pytest.raises(ValueError, match="test set would have"):
        _athena_ts_split(sales, test_periods=len(sales))


def test_seasonal_naive_repeats_the_last_season_and_widens():
    y = np.tile([10.0, 20, 30, 40, 50, 60, 70], 10) + np.random.default_rng(0).normal(0, 1, 70)
    fc, lo, hi = _athena_forecast(y, 14, "seasonal_naive", season=7)
    assert np.allclose(fc, np.concatenate([y[-7:], y[-7:]]))
    width = hi - lo
    assert np.allclose(width[:7], width[0]) and width[7] > width[0]  # one more season ahead = more uncertainty


def test_gbm_lags_extrapolates_a_trend():
    y = 100 + 2.0 * np.arange(200) + np.tile([0.0, 3, -2, 1, 5, -4, 2], 30)[:200]
    fc, lo, _ = _athena_forecast(y, 21, "gbm_lags", season=7)
    assert np.isnan(lo).all()  # point forecasts only
    assert abs(fc[-1] - (100 + 2.0 * 220)) < 15  # differencing keeps the trend going (levels-only trees would flatten)


def test_forecaster_with_test_set_beats_the_naive_baseline(sales):
    train, test = _athena_ts_split(sales, test_periods=28)
    naive = ForecasterHandler()(_ctx({"method": "seasonal_naive"}, [train, test])).metrics
    for method in ("ets", "arima", "gbm_lags"):
        res = ForecasterHandler()(_ctx({"method": method}, [train, test]))
        table, report = res.outputs
        assert list(table.columns) == ["date", "actual", "forecast", "lower", "upper"] and len(table) == 28
        assert report["mase"] < naive["mase"], method
        assert res.preview.kind == "plot"
    assert 0.6 <= ForecasterHandler()(_ctx({"method": "ets"}, [train, test])).metrics["coverage"] <= 1.0


def test_forecaster_without_test_forecasts_future_dates(sales):
    table, report = ForecasterHandler()(_ctx({"method": "ets", "horizon": 10}, [sales])).outputs
    assert len(table) == 10 and "mae" not in report
    assert table["date"].iloc[0] == pd.Timestamp("2026-01-01") and table["date"].iloc[-1] == pd.Timestamp("2026-01-10")
    assert (table["lower"] < table["forecast"]).all() and (table["forecast"] < table["upper"]).all()
    monthly = _frame(np.linspace(10, 40, 48) + np.tile(np.arange(12.0), 4), freq="MS", name="target")
    t, r = ForecasterHandler()(_ctx({"method": "seasonal_naive", "horizon": 3}, [monthly])).outputs
    assert r["season_length"] == 12 and t["date"].dt.day.eq(1).all()


def test_forecaster_errors(sales):
    train, test = _athena_ts_split(sales, test_periods=28)
    with pytest.raises(ValueError, match="must come after"):
        ForecasterHandler()(_ctx({"method": "seasonal_naive"}, [test, train]))
    with pytest.raises(ValueError, match="positive values"):
        ForecasterHandler()(_ctx({"method": "ets", "ets_seasonal": "mul"}, [train.assign(sales=train["sales"] - 400), None]))


def test_statsmodels_methods_need_the_extra(monkeypatch, sales):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "statsmodels" else real(name, *a))
    with pytest.raises(RuntimeError, match="uv sync --extra stats"):
        ForecasterHandler()(_ctx({"method": "arima"}, [sales]))
    assert ForecasterHandler()(_ctx({"method": "seasonal_naive", "horizon": 3}, [sales])).outputs[0].shape[0] == 3


def test_metrics_by_hand():
    m = _athena_forecast_metrics(actual=[10, 0, 20], forecast=[12, 1, 18], train=[1, 2, 4, 7], season=1,
                                 lower=[11, -1, 19], upper=[13, 2, 21])
    assert m["mae"] == pytest.approx(5 / 3) and m["rmse"] == pytest.approx(np.sqrt(9 / 3))
    assert m["mape"] == pytest.approx((0.2 + 0.1) / 2 * 100)  # the zero actual is skipped
    assert m["mase"] == pytest.approx((5 / 3) / 2)  # naive one-step error on train: mean(|1|,|2|,|3|) = 2
    assert m["coverage"] == pytest.approx(2 / 3)  # 0 and 20 fall inside their intervals, 10 does not
    assert "mape" not in _athena_forecast_metrics([0, 0], [1, 1], [1, 2, 3])


def test_backtest_folds(sales):
    res = BacktestHandler()(_ctx({"method": "seasonal_naive", "folds": 4, "horizon": 14, "step": 7}, [sales]))
    folds, report = res.outputs
    assert len(folds) == 4 and report["folds"] == 4
    starts = pd.to_datetime(folds["test_start"])
    assert (starts.diff().dropna() == pd.Timedelta(days=7)).all() and starts.iloc[-1] == pd.Timestamp("2025-12-18")
    assert report["mean_mae"] == pytest.approx(folds["mae"].mean())
    with pytest.raises(ValueError, match="Not enough history"):
        BacktestHandler()(_ctx({"method": "seasonal_naive", "folds": 50, "horizon": 28}, [sales.head(200)]))
