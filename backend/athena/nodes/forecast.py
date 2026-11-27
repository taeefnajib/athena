"""Time-series nodes: chronological split, forecaster (with intervals and accuracy), rolling-origin backtest.

The computations live in forecast_core.py (copied verbatim into exports); this module adds configuration,
logging and plots.
"""
from __future__ import annotations

import importlib.util
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.nodes.forecast_core import (
    _athena_backtest_table,
    _athena_forecast_table,
    _athena_series,
    _athena_ts_split,
)
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe
from athena.utils.plotting import SERIES, fig_to_plot_preview, style_axes

HISTORY, ACTUAL, FORECAST = "#9a9a9a", "#191919", SERIES[0]
NEEDS_STATSMODELS = {"ets", "arima"}


class ForecastSettings(BaseModel):
    date_col: str = ""
    target: str = ""
    method: Literal["seasonal_naive", "ets", "arima", "gbm_lags"] = "ets"
    season_length: int = Field(0, ge=0, le=1000)
    ets_trend: Literal["add", "damped", "none"] = "add"
    ets_seasonal: Literal["add", "mul", "none"] = "add"
    arima_order: str = "1,1,1"
    seasonal_order: str = "0,1,1"
    lags: str = ""
    interval: float = Field(0.9, gt=0.5, lt=1.0)


FORECAST_FIELDS = {
    "date_col": ui("Date column", help="Empty = the first date column."),
    "target": ui("Target", help="The numeric column to forecast. Empty = a column named target, or the only numeric column."),
    "method": ui("Method", help="seasonal_naive repeats the last season (the baseline to beat); ets = exponential smoothing "
                                "(Holt-Winters); arima = seasonal ARIMA; gbm_lags = gradient boosting on lagged changes."),
    "season_length": ui("Season length", help="Steps per cycle (7 for daily data with a weekly pattern). 0 = from the frequency."),
    "ets_trend": ui("ETS trend"), "ets_seasonal": ui("ETS seasonality"),
    "arima_order": ui("ARIMA order (p,d,q)"), "seasonal_order": ui("Seasonal order (P,D,Q)"),
    "lags": ui("Lags (gbm_lags)", help="Comma-separated, e.g. 1,2,3,7,14. Empty = 1-7 plus the season length."),
    "interval": ui("Prediction interval", help="0.9 = a 90% interval. Not available for gbm_lags."),
}


def _settings(cfg: BaseModel) -> dict[str, Any]:
    return {k: v for k, v in cfg.model_dump().items() if k in ForecastSettings.model_fields or k in ("horizon", "folds", "step")}


def _check_method(method: str) -> None:
    if method in NEEDS_STATSMODELS and importlib.util.find_spec("statsmodels") is None:
        raise RuntimeError(f"The {method} method needs statsmodels: uv sync --extra stats (or use seasonal_naive / gbm_lags)")


@node(
    "ts_split", label="Time Series Split", category="forecast",
    description="Sort by date and hold out the most recent rows as the test set (never shuffled)",
    inputs=[Port("dataset", "dataset")], outputs=[Port("train", "dataset"), Port("test", "dataset")],
    fields={"date_col": ui("Date column", help="Empty = the first date column."),
            "test_periods": ui("Test periods", help="Rows to hold out. 0 = use Test fraction."),
            "test_fraction": ui("Test fraction")},
    code=EXPORT["ts_split"],
)
class TsSplitHandler:
    class Config(BaseModel):
        date_col: str = ""
        test_periods: int = Field(0, ge=0)
        test_fraction: float = Field(0.2, gt=0, lt=1)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        train, test = _athena_ts_split(ctx.inputs[0], cfg.date_col, cfg.test_periods, cfg.test_fraction)
        ctx.logger.info("Split by time", train=len(train), test=len(test))
        return HandlerResult(outputs=[train, test], preview=preview_dataframe(test),
                             metrics={"train_rows": float(len(train)), "test_rows": float(len(test))})


@node(
    "forecaster", label="Forecaster", category="forecast",
    description="Forecast a time series with intervals; with a test set connected, also MAE, RMSE, MAPE, sMAPE and MASE",
    inputs=[Port("train", "dataset"), Port("test", "dataset", optional=True)],
    outputs=[Port("forecast", "dataset"), Port("report", "report")],
    fields={**FORECAST_FIELDS, "horizon": ui("Horizon", help="Steps to forecast when no test set is connected.")},
    code=EXPORT["forecaster"],
)
class ForecasterHandler:
    class Config(ForecastSettings):
        horizon: int = Field(14, ge=1, le=10_000)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        _check_method(cfg.method)
        train, test = ctx.inputs[0], ctx.inputs[1] if len(ctx.inputs) > 1 else None
        table, report = _athena_forecast_table(train, test, _settings(cfg))
        dates, y, _, target, freq = _athena_series(train, cfg.date_col, cfg.target)
        ctx.logger.info("Forecast", method=cfg.method, horizon=len(table), frequency=freq, season=int(report["season_length"]))
        if cfg.method == "gbm_lags":
            ctx.logger.info("gbm_lags gives point forecasts only (no interval)")
        if test is not None:
            ctx.logger.info("Accuracy on the test period", **{k: round(v, 4) for k, v in report.items() if k not in ("horizon", "season_length")})
        fig = _forecast_plot(dates, y, table, target, cfg.method, report)
        return HandlerResult(outputs=[table, report], preview=fig_to_plot_preview(fig), metrics=report)


@node(
    "backtest", label="Backtest", category="forecast",
    description="Rolling-origin evaluation: refit on an expanding window and forecast the next steps, several times",
    inputs=[Port("dataset", "dataset")], outputs=[Port("folds", "dataset"), Port("report", "report")],
    fields={**FORECAST_FIELDS, "horizon": ui("Horizon"), "folds": ui("Folds"),
            "step": ui("Step", help="Steps between fold origins. 0 = the horizon (back-to-back test windows).")},
    code=EXPORT["backtest"],
)
class BacktestHandler:
    class Config(ForecastSettings):
        horizon: int = Field(14, ge=1, le=10_000)
        folds: int = Field(3, ge=1, le=50)
        step: int = Field(0, ge=0)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        _check_method(cfg.method)
        table, report, segments = _athena_backtest_table(ctx.inputs[0], _settings(cfg))
        for row in table.to_dict("records"):
            ctx.logger.info(f"Fold {row['fold']}", test_start=str(row["test_start"])[:10], mae=round(row["mae"], 4))
        dates, y, _, target, _ = _athena_series(ctx.inputs[0], cfg.date_col, cfg.target)
        return HandlerResult(outputs=[table, report], preview=fig_to_plot_preview(_backtest_plot(dates, y, segments, target, cfg.method, report)),
                             metrics=report)


def _history_window(dates: pd.Series, y: np.ndarray, keep: int) -> tuple[pd.Series, np.ndarray]:
    return dates.iloc[-keep:], y[-keep:]


def _forecast_plot(dates: pd.Series, y: np.ndarray, table: pd.DataFrame, target: str, method: str, report: dict[str, float]) -> Any:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.2))
    hd, hy = _history_window(dates, y, max(4 * len(table), 60))
    ax.plot(hd, hy, color=HISTORY, lw=1.5, label="History")
    if not table["lower"].isna().all():
        ax.fill_between(table["date"], table["lower"], table["upper"], color=FORECAST, alpha=0.15, lw=0, label="Interval")
    if "actual" in table:
        ax.plot(table["date"], table["actual"], color=ACTUAL, lw=1.5, label="Actual")
    ax.plot(table["date"], table["forecast"], color=FORECAST, lw=2, label="Forecast")
    score = f" · MAE {report['mae']:.3g} · MASE {report['mase']:.2f}" if "mase" in report else (f" · MAE {report['mae']:.3g}" if "mae" in report else "")
    ax.set_title(f"{target}: {method}{score}", fontsize=11, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8.5, frameon=False)
    style_axes(ax)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def _backtest_plot(dates: pd.Series, y: np.ndarray, segments: list[Any], target: str, method: str, report: dict[str, float]) -> Any:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.2))
    span = sum(len(s[0]) for s in segments)
    hd, hy = _history_window(dates, y, max(3 * span, 90))
    ax.plot(hd, hy, color=HISTORY, lw=1.5, label="Actual")
    for i, (d, _, fc) in enumerate(segments):
        ax.plot(d, fc, color=FORECAST, lw=2, label="Forecast per fold" if i == 0 else None)
        ax.axvline(d[0], color="#cccccc", lw=0.8)
    ax.set_title(f"{target}: {method} backtest · mean MAE {report['mean_mae']:.3g}", fontsize=11, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8.5, frameon=False)
    style_axes(ax)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
