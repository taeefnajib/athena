"""Forecasting core: pure, self-contained functions shared by the nodes and copied verbatim into exported
scripts (each imports what it needs), so Athena and the export compute exactly the same forecasts.

One series per table: a date column and a numeric target, at a regular frequency.
"""
from __future__ import annotations


def _athena_date_col(df, date_col=""):
    """The date column: the one you named, else the first datetime column, else the first text column of dates."""
    import pandas as pd
    cols = list(df.columns)
    dc = str(date_col).strip()
    if dc:
        if dc not in cols:
            raise ValueError(f"Date column {dc!r} isn't in the data")
        return dc
    for c in cols:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    for c in cols:
        s = df[c]
        if (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)) and                 pd.to_datetime(s.head(50), errors="coerce", format="mixed").notna().all():
            return c
    raise ValueError("No date column found: set Date column")


def _athena_series(df, date_col="", target=""):
    """(dates, values, date column, target column, frequency) from a table, sorted by date."""
    import pandas as pd
    cols = list(df.columns)
    dc = _athena_date_col(df, date_col)
    numeric = [c for c in cols if c != dc and pd.api.types.is_numeric_dtype(df[c])]
    tc = target.strip() or ("target" if "target" in numeric else (numeric[0] if len(numeric) == 1 else ""))
    if not tc:
        raise ValueError(f"Several numeric columns ({', '.join(map(str, numeric[:5]))}): set Target")
    if tc not in cols:
        raise ValueError(f"Target column {tc!r} isn't in the data")
    d = pd.DataFrame({"date": pd.to_datetime(df[dc], format="mixed"), "y": pd.to_numeric(df[tc], errors="coerce")})
    d = d.sort_values("date", kind="stable").reset_index(drop=True)
    if d["date"].duplicated().any():
        raise ValueError(f"{int(d['date'].duplicated().sum())} repeated dates: forecast one series at a time "
                         "(aggregate first, e.g. SQL Transform with GROUP BY date)")
    if d["y"].isna().any():
        raise ValueError(f"The target has {int(d['y'].isna().sum())} missing values: impute them first")
    freq = pd.infer_freq(d["date"]) if len(d) >= 3 else None
    if freq is None:
        raise ValueError("Dates aren't evenly spaced (gaps or mixed steps): resample to a regular frequency first")
    return d["date"], d["y"].to_numpy(dtype=float), dc, tc, freq


def _athena_season(freq, season_length=0):
    """Season length: the one you set, else the usual cycle for the frequency (7 for daily, 12 for monthly...)."""
    import pandas as pd
    if int(season_length) > 0:
        return int(season_length)
    base = pd.tseries.frequencies.to_offset(freq).name.split("-")[0]
    return {"D": 7, "B": 5, "W": 52, "MS": 12, "ME": 12, "M": 12, "QS": 4, "QE": 4, "Q": 4, "h": 24, "H": 24}.get(base, 1)


def _athena_forecast(y, h, method="ets", season=1, arima_order="1,1,1", seasonal_order="0,1,1",
                     ets_trend="add", ets_seasonal="add", lags="", interval=0.9):
    """Forecast h steps after the series y. Returns (forecast, lower, upper); bounds are NaN when unavailable."""
    import numpy as np
    import pandas as pd
    from scipy.stats import norm
    y = np.asarray(y, dtype=float)
    n, h = len(y), int(h)
    m = int(season) if int(season) > 1 and n >= 2 * int(season) else 1
    z = norm.ppf(0.5 + interval / 2)
    if method == "seasonal_naive":
        steps = np.arange(h)
        fc = y[n - m + steps % m]
        resid = y[m:] - y[:-m]
        se = (resid.std(ddof=1) if len(resid) > 1 else 0.0) * np.sqrt(steps // m + 1)
        return fc, fc - z * se, fc + z * se
    if method == "ets":
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        seasonal = None if ets_seasonal == "none" or m == 1 else ets_seasonal
        if seasonal == "mul" and (y <= 0).any():
            raise ValueError("Multiplicative seasonality needs positive values: use additive")
        res = ETSModel(pd.Series(y), error="add", trend=None if ets_trend == "none" else "add",
                       damped_trend=ets_trend == "damped", seasonal=seasonal,
                       seasonal_periods=m if seasonal else None).fit(disp=False)
        f = res.get_prediction(start=n, end=n + h - 1).summary_frame(alpha=1 - interval)
        return f["mean"].to_numpy(), f["pi_lower"].to_numpy(), f["pi_upper"].to_numpy()
    if method == "arima":
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        order = tuple(int(v) for v in str(arima_order).split(","))
        sorder = (*(int(v) for v in str(seasonal_order).split(",")), m) if m > 1 else (0, 0, 0, 0)
        if len(order) != 3 or len(sorder) != 4:
            raise ValueError("ARIMA orders are three numbers, like 1,1,1")
        f = SARIMAX(y, order=order, seasonal_order=sorder).fit(disp=False).get_forecast(h)
        ci = np.asarray(f.conf_int(alpha=1 - interval))
        return np.asarray(f.predicted_mean), ci[:, 0], ci[:, 1]
    if method == "gbm_lags":
        from sklearn.ensemble import HistGradientBoostingRegressor
        chosen = {int(v) for v in str(lags).split(",") if v.strip()}
        L = sorted(chosen or set(range(1, 8)) | ({m} if m > 1 else set()))
        d = np.diff(y)  # model the changes: trees can't extrapolate a trend in the levels
        p = max(L)
        if len(d) <= p + 10:
            raise ValueError(f"Too short for lags up to {p}: needs more than {p + 12} points")
        X = np.column_stack([d[p - lag: len(d) - lag] for lag in L])
        model = HistGradientBoostingRegressor(random_state=0).fit(X, d[p:])
        hist, level, out = list(d), y[-1], []
        for _ in range(h):  # recursive: each forecast step feeds the next step's lags
            step = float(model.predict(np.array([[hist[-lag] for lag in L]]))[0])
            hist.append(step)
            level += step
            out.append(level)
        nan = np.full(h, np.nan)
        return np.array(out), nan, nan
    raise ValueError(f"Unknown method {method!r}")


def _athena_forecast_metrics(actual, forecast, train, season=1, lower=None, upper=None):
    """MAE, RMSE, MAPE (zeros skipped), sMAPE, MASE (scaled by the seasonal-naive error on train), coverage."""
    import numpy as np
    a, f, tr = (np.asarray(v, dtype=float) for v in (actual, forecast, train))
    e = a - f
    m = int(season) if int(season) > 1 and len(tr) > int(season) else 1
    out = {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))),
           "smape": float(np.mean(2 * np.abs(e) / np.maximum(np.abs(a) + np.abs(f), 1e-12)) * 100)}
    if (a != 0).any():
        out["mape"] = float(np.mean(np.abs(e[a != 0] / a[a != 0])) * 100)
    scale = np.mean(np.abs(tr[m:] - tr[:-m])) if len(tr) > m else 0.0
    if scale > 0:
        out["mase"] = float(np.mean(np.abs(e)) / scale)
    if lower is not None and not np.isnan(np.asarray(lower, dtype=float)).all():
        out["coverage"] = float(np.mean((a >= np.asarray(lower, dtype=float)) & (a <= np.asarray(upper, dtype=float))))
    return out


def _athena_forecast_table(train, test=None, cfg=None):
    """Fit on the train table and forecast the test period (or cfg['horizon'] steps). Returns (table, report)."""
    import pandas as pd
    cfg = cfg or {}
    dates, y, _, _, freq = _athena_series(train, cfg.get("date_col", ""), cfg.get("target", ""))
    season = _athena_season(freq, cfg.get("season_length", 0))
    if test is not None:
        future, actual, _, _, _ = _athena_series(test, cfg.get("date_col", ""), cfg.get("target", ""))
        if future.iloc[0] <= dates.iloc[-1]:
            raise ValueError("The test period must come after the training period (use Time Series Split)")
    else:
        future = pd.Series(pd.date_range(dates.iloc[-1], periods=int(cfg.get("horizon", 14)) + 1, freq=freq)[1:])
        actual = None
    keys = ("method", "arima_order", "seasonal_order", "ets_trend", "ets_seasonal", "lags", "interval")
    fc, lo, hi = _athena_forecast(y, len(future), season=season, **{k: cfg[k] for k in keys if k in cfg})
    table = pd.DataFrame({"date": future.to_numpy(), "forecast": fc, "lower": lo, "upper": hi})
    report = {"horizon": float(len(future)), "season_length": float(season)}
    if actual is not None:
        table.insert(1, "actual", actual)
        report.update(_athena_forecast_metrics(actual, fc, y, season, lo, hi))
    return table, report


def _athena_backtest_table(df, cfg=None):
    """Rolling-origin backtest: refit on an expanding window and forecast the next `horizon` points, `folds` times.
    Returns (per-fold metrics table, mean report, list of (dates, actual, forecast) per fold)."""
    import pandas as pd
    cfg = cfg or {}
    dates, y, _, _, freq = _athena_series(df, cfg.get("date_col", ""), cfg.get("target", ""))
    season = _athena_season(freq, cfg.get("season_length", 0))
    h, folds = int(cfg.get("horizon", 14)), int(cfg.get("folds", 3))
    step = int(cfg.get("step", 0)) or h
    first = len(y) - h - (folds - 1) * step
    if first < max(2 * season, 20):
        raise ValueError(f"Not enough history for {folds} folds of {h} steps: use fewer folds or a shorter horizon")
    keys = ("method", "arima_order", "seasonal_order", "ets_trend", "ets_seasonal", "lags", "interval")
    rows, segments = [], []
    for k in range(folds):
        o = first + k * step
        fc, lo, hi = _athena_forecast(y[:o], h, season=season, **{key: cfg[key] for key in keys if key in cfg})
        scores = _athena_forecast_metrics(y[o:o + h], fc, y[:o], season, lo, hi)
        rows.append({"fold": k + 1, "train_end": dates.iloc[o - 1], "test_start": dates.iloc[o], **scores})
        segments.append((dates.iloc[o:o + h].to_numpy(), y[o:o + h], fc))
    table = pd.DataFrame(rows)
    report = {f"mean_{c}": float(table[c].mean()) for c in table.columns
              if c not in ("fold", "train_end", "test_start") and table[c].notna().any()}
    report.update({"folds": float(folds), "horizon": float(h)})
    return table, report, segments


def _athena_ts_split(df, date_col="", test_periods=0, test_fraction=0.2):
    """Chronological split: sort by date and keep the last rows as the test set (never shuffled)."""
    import pandas as pd
    dc = _athena_date_col(df, date_col)
    d = df.assign(_t=pd.to_datetime(df[dc], format="mixed")).sort_values("_t", kind="stable").drop(columns="_t").reset_index(drop=True)
    n_test = int(test_periods) or round(len(d) * float(test_fraction))
    if not 0 < n_test < len(d):
        raise ValueError(f"The test set would have {n_test} of {len(d)} rows: change Test periods / Test fraction")
    return d.iloc[:-n_test].reset_index(drop=True), d.iloc[-n_test:].reset_index(drop=True)
