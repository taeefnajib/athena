"""Export templates: time series (split, forecaster, backtest) and clustering. They call the same helpers as the
nodes (``_athena_forecast_table``, ``_athena_cluster_matrix``, ...), which codegen copies into the script."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]

FORECAST_KEYS = ("date_col", "target", "method", "season_length", "ets_trend", "ets_seasonal", "arima_order",
                 "seasonal_order", "lags", "interval", "horizon", "folds", "step")


def _cfg(v: V) -> str:
    return repr({k: v[k] for k in FORECAST_KEYS if k in v})


def ts_split(v: V) -> str:
    return lines(f"{v['out_train']}, {v['out_test']} = _athena_ts_split({v['in_dataset']}, {v['date_col']!r}, "
                 f"{int(v['test_periods'])}, {float(v['test_fraction'])})",
                 f"print('Train', len({v['out_train']}), 'rows | test', len({v['out_test']}), 'rows')")


def forecaster(v: V) -> str:
    table, rep = v["out_forecast"], v["out_report"]
    return lines(f"{table}, {rep} = _athena_forecast_table({v['in_train']}, {v['in_test']}, {_cfg(v)})",
                 f"print({table}.head())", f"print({rep})")


def backtest(v: V) -> str:
    folds, rep = v["out_folds"], v["out_report"]
    return lines(f"{folds}, {rep}, _segments = _athena_backtest_table({v['in_dataset']}, {_cfg(v)})",
                 f"print({folds})", f"print({rep})")


def _matrix(v: V, label: str = "cluster") -> str:
    return f"_X, _names = _athena_cluster_matrix({v['in_dataset']}, {v['cols']!r}, {bool(v['scale'])}, {label!r})"


def _labelled(v: V, labels: str) -> str:
    out = v["out_dataset"]
    return lines(f"{out} = {v['in_dataset']}.copy()", f"{out}['cluster'] = {labels}",
                 f"print(_athena_cluster_profile({v['in_dataset']}, {out}['cluster'].to_numpy(), _names))")


def kmeans(v: V) -> str:
    rs = int(v["random_state"])
    k = (f"_k = {int(v['n_clusters'])}" if int(v["n_clusters"])
         else f"_k, _scores = _athena_auto_k(_X, {int(v['k_max'])}, {rs})\nprint('Silhouette by k:', _scores)")
    km = f"KMeans(n_clusters=_k, n_init=10, random_state={rs})"
    fit = (f"{v['out_model']} = make_pipeline(StandardScaler(), _km).fit({v['in_dataset']}[_names])" if v["scale"]
           else f"{v['out_model']} = _km.fit({v['in_dataset']}[_names])")
    return lines("from sklearn.cluster import KMeans", "from sklearn.pipeline import make_pipeline",
                 "from sklearn.preprocessing import StandardScaler",
                 _matrix(v), k, f"_km = {km}", fit) + _labelled(v, "_km.labels_")


def agglomerative(v: V) -> str:
    return lines("from sklearn.cluster import AgglomerativeClustering", _matrix(v),
                 f"_labels = AgglomerativeClustering(n_clusters={int(v['n_clusters'])}, linkage={v['linkage']!r}).fit_predict(_X)") \
        + _labelled(v, "_labels")


def dbscan(v: V) -> str:
    return lines("from sklearn.cluster import DBSCAN", _matrix(v),
                 f"_labels = DBSCAN(eps={float(v['eps'])}, min_samples={int(v['min_samples'])}).fit_predict(_X)") \
        + _labelled(v, "_labels")


def cluster_eval(v: V) -> str:
    src, label = v["in_dataset"], v["label_col"]
    return lines(f"_X, _names = _athena_cluster_matrix({src}, {v['cols']!r}, {bool(v['scale'])}, {label!r})",
                 f"{v['out_report']} = _athena_cluster_report(_X, {src}[{label!r}].to_numpy())",
                 f"{v['out_profile']} = _athena_cluster_profile({src}, {src}[{label!r}].to_numpy(), _names)",
                 f"print({v['out_report']})", f"print({v['out_profile']})")


EXPORT: dict[str, Template] = {"ts_split": ts_split, "forecaster": forecaster, "backtest": backtest, "kmeans": kmeans,
                               "agglomerative": agglomerative, "dbscan": dbscan, "cluster_eval": cluster_eval}
