"""Monitoring with Evidently: data drift, prediction drift and data quality between a reference table (usually the
training data) and a current one (new data, or the requests a deployed endpoint received).

Each node returns a report a Quality Gate can check (``drifted_columns == 0``, ``prediction_drift == 0``,
``missing_share <= 0.05``), a per-column table, and Evidently's full interactive HTML report (``HandlerResult.documents``,
opened from the inspector). The ``_athena_*`` helpers are self-contained and copied verbatim into exported scripts.
Evidently is an optional extra (``athena-backend[monitoring]``), imported only when a node runs.
"""
from __future__ import annotations

import importlib.util
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe

INSTALL_HINT = "Evidently isn't installed. Install it with: uv sync --extra monitoring (or pip install evidently)"

NumMethod = Literal["auto", "ks", "wasserstein", "psi", "jensenshannon", "kl_div", "anderson", "cramer_von_mises", "t_test", "mannw"]
CatMethod = Literal["auto", "chisquare", "z", "psi", "jensenshannon", "kl_div", "TVD", "g_test", "fisher_exact"]


def _athena_evidently_drift(current, reference, columns="", num_method="auto", cat_method="auto",
                            num_threshold=0.0, cat_threshold=0.0, drift_share=0.5):
    """Evidently data drift of ``current`` against ``reference``. Thresholds of 0 use each method's default.
    Returns (report, table, snapshot): report holds numbers for Quality Gates, table one row per column."""
    import pandas as pd
    from evidently import Report
    from evidently.presets import DataDriftPreset
    shared = [c for c in reference.columns if c in current.columns]
    cols = [c.strip() for c in str(columns).split(",") if c.strip()] or shared
    missing = [c for c in cols if c not in shared]
    if missing:
        raise ValueError(f"Column(s) {missing} must be in both tables. Shared columns: {shared}")
    if not cols:
        raise ValueError("The current and reference tables have no columns in common")
    if len(current) == 0 or len(reference) == 0:
        raise ValueError("Both tables need at least one row")
    kw = {"columns": cols, "drift_share": float(drift_share)}
    if num_method != "auto":
        kw["num_method"] = num_method
    if cat_method != "auto":
        kw["cat_method"] = cat_method
    if num_threshold:
        kw["num_threshold"] = float(num_threshold)
    if cat_threshold:
        kw["cat_threshold"] = float(cat_threshold)
    snapshot = Report([DataDriftPreset(**kw)], include_tests=True).run(
        current_data=current[cols].reset_index(drop=True), reference_data=reference[cols].reset_index(drop=True))
    result = snapshot.dict()
    rows, count, share = {}, 0.0, 0.0
    for m in result["metrics"]:
        cfg = m["config"]
        kind = str(cfg.get("type", ""))
        if kind.endswith("DriftedColumnsCount"):
            count, share = float(m["value"]["count"]), float(m["value"]["share"])
        elif kind.endswith("ValueDrift"):
            rows[cfg["column"]] = {"column": cfg["column"], "method": str(cfg.get("method")),
                                   "threshold": float(cfg.get("threshold")), "score": float(m["value"]), "drifted": False}
    for t in result["tests"]:
        params = t.get("metric_config", {}).get("params", {})
        if str(params.get("type", "")).endswith("ValueDrift") and params.get("column") in rows:
            rows[params["column"]]["drifted"] = str(getattr(t["status"], "value", t["status"])).upper() == "FAIL"
    table = pd.DataFrame([rows[c] for c in cols if c in rows], columns=["column", "method", "threshold", "score", "drifted"])
    report = {"dataset_drift": float(share >= float(drift_share)), "drifted_columns": count,
              "columns_checked": float(len(table)), "share_drifted": share,
              **{f"drift_score.{r['column']}": r["score"] for r in table.to_dict("records")}}
    return report, table, snapshot


def _athena_prediction_drift(model, reference, current, num_method="auto", cat_method="auto", num_threshold=0.0, cat_threshold=0.0):
    """Drift of the model's predictions (and, for a binary classifier, its probability of the second class) on
    ``current`` against ``reference``. Returns (report, table, snapshot)."""
    import pandas as pd
    features = [str(c) for c in getattr(model, "feature_names_in_", [])] or [c for c in reference.columns if c in current.columns]
    for name, X in (("reference", reference), ("current", current)):
        missing = [c for c in features if c not in X.columns]
        if missing:
            raise ValueError(f"The {name} table lacks the model's feature(s) {missing}")

    def outputs(X):
        X = X[features]
        out = pd.DataFrame({"prediction": model.predict(X)})
        if hasattr(model, "predict_proba") and len(getattr(model, "classes_", [])) == 2:
            out["probability"] = model.predict_proba(X)[:, 1]
        return out

    report, table, snapshot = _athena_evidently_drift(outputs(current), outputs(reference), "", num_method, cat_method,
                                                      num_threshold, cat_threshold, 0.5)
    by = {r["column"]: r for r in table.to_dict("records")}
    report = {"prediction_drift": float(by["prediction"]["drifted"]), "prediction_drift_score": by["prediction"]["score"]}
    if "probability" in by:
        report.update(probability_drift=float(by["probability"]["drifted"]), probability_drift_score=by["probability"]["score"])
    return report, table, snapshot


def _athena_data_quality(current, reference=None):
    """Evidently data summary of ``current`` (and ``reference``, when given, side by side).
    Returns (report, table, snapshot): table has one row per column, report the table-level numbers."""
    import pandas as pd
    from evidently import Report
    from evidently.presets import DataSummaryPreset

    def summarise(df):
        snap = Report([DataSummaryPreset()]).run(current_data=df.reset_index(drop=True), reference_data=None)
        totals, cols = {}, {}
        names = {"RowCount": "rows", "DuplicatedRowCount": "duplicated_rows", "DuplicatedColumnsCount": "duplicated_columns",
                 "AlmostDuplicatedColumnsCount": "almost_duplicated_columns", "AlmostConstantColumnsCount": "almost_constant_columns",
                 "EmptyRowsCount": "empty_rows", "EmptyColumnsCount": "empty_columns", "ConstantColumnsCount": "constant_columns"}
        stats = {"MinValue": "min", "MaxValue": "max", "MeanValue": "mean", "StdValue": "std"}
        for m in snap.dict()["metrics"]:
            cfg, value = m["config"], m["value"]
            kind = str(cfg.get("type", "")).rsplit(":", 1)[-1]
            col = cfg.get("column")
            if kind in names:
                totals[names[kind]] = float(value)
            elif kind == "ColumnCount" and cfg.get("column_type") is None:
                totals["columns"] = float(value)
            elif kind == "DatasetMissingValueCount":  # Evidently's share is per row (it can pass 1): use cells
                totals["missing_values"] = float(value["count"])
                totals["missing_share"] = float(value["count"]) / max(df.size, 1)
            elif col is not None and kind == "MissingValueCount":
                cols.setdefault(col, {})["missing_share"] = float(value["share"])
            elif col is not None and kind == "UniqueValueCount":
                cols.setdefault(col, {})["unique"] = float(len(value["counts"]))
            elif col is not None and kind in stats:
                cols.setdefault(col, {})[stats[kind]] = float(value)
        for c in df.columns:  # a numeric column's distinct count, which Evidently reports for categories only
            cols.setdefault(c, {}).setdefault("unique", float(df[c].nunique()))
        return totals, cols, snap

    totals, cur_cols, snapshot = summarise(current)
    report = dict(totals)
    fields = ["missing_share", "unique", "mean", "std", "min", "max"]
    rows = [{"column": c, **{f: cur_cols.get(c, {}).get(f) for f in fields}} for c in current.columns]
    if reference is not None:
        ref_totals, ref_cols, _ = summarise(reference)
        shared = [c for c in current.columns if c in reference.columns]
        if shared:  # the HTML report shows both side by side (Evidently needs the same columns in both)
            snapshot = Report([DataSummaryPreset()]).run(current_data=current[shared].reset_index(drop=True),
                                                         reference_data=reference[shared].reset_index(drop=True))
        report.update({f"reference.{k}": v for k, v in ref_totals.items()})
        for r in rows:
            for f in ("missing_share", "mean"):
                r[f"reference_{f}"] = ref_cols.get(r["column"], {}).get(f)
        report["new_columns"] = float(len([c for c in current.columns if c not in reference.columns]))
        report["missing_columns"] = float(len([c for c in reference.columns if c not in current.columns]))
    return report, pd.DataFrame(rows), snapshot


def _need_evidently() -> None:
    if importlib.util.find_spec("evidently") is None:
        raise ValueError(INSTALL_HINT)


def _html(snapshot: Any) -> dict[str, str]:
    return {"report.html": snapshot.get_html_str(as_iframe=False)}


_METHOD_FIELDS = {
    "num_method": ui("Numeric test"), "cat_method": ui("Categorical test"),
    "num_threshold": ui("Numeric threshold (0 = test default)"), "cat_threshold": ui("Categorical threshold (0 = test default)"),
}


class _Methods(BaseModel):
    num_method: NumMethod = "auto"
    cat_method: CatMethod = "auto"
    num_threshold: float = Field(0.0, ge=0)
    cat_threshold: float = Field(0.0, ge=0)


@node(
    "evidently_drift", label="Data Drift Report", category="monitor",
    description="Evidently data drift: which columns of the current table moved away from the reference (training) data",
    inputs=[Port("current", "dataset"), Port("reference", "dataset")],
    outputs=[Port("report", "report"), Port("columns", "dataset")],
    fields={"columns": ui("Columns (blank = all shared)"), **_METHOD_FIELDS,
            "drift_share": ui("Dataset drifts when this share of columns drift")},
    code=EXPORT["evidently_drift"],
)
class EvidentlyDriftHandler:
    class Config(_Methods):
        columns: str = ""
        drift_share: float = Field(0.5, gt=0, le=1)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        _need_evidently()
        current: pd.DataFrame = ctx.inputs[0]
        reference: pd.DataFrame = ctx.inputs[1]
        report, table, snapshot = _athena_evidently_drift(current, reference, cfg.columns, cfg.num_method, cfg.cat_method,
                                                          cfg.num_threshold, cfg.cat_threshold, cfg.drift_share)
        drifted = table.loc[table["drifted"], "column"].tolist()
        ctx.logger.info(f"{len(drifted)} of {len(table)} column(s) drifted" + (f": {', '.join(map(str, drifted))}" if drifted else ""))
        if report["dataset_drift"]:
            ctx.logger.warning(f"Dataset drift: {report['share_drifted']:.0%} of columns drifted (limit {cfg.drift_share:.0%})")
        return HandlerResult(outputs=[report, table], preview=preview_dataframe(table), documents=_html(snapshot),
                             metrics={k: report[k] for k in ("dataset_drift", "drifted_columns", "columns_checked", "share_drifted")})


@node(
    "prediction_drift", label="Prediction Drift", category="monitor",
    description="Evidently drift of the model's predictions (and probabilities) on current data against reference data",
    inputs=[Port("model", "model"), Port("reference", "dataset"), Port("current", "dataset")],
    outputs=[Port("report", "report"), Port("columns", "dataset")],
    fields=_METHOD_FIELDS,
    code=EXPORT["prediction_drift"],
)
class PredictionDriftHandler:
    class Config(_Methods):
        pass

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        _need_evidently()
        model, reference, current = ctx.inputs
        report, table, snapshot = _athena_prediction_drift(model, reference, current, cfg.num_method, cfg.cat_method,
                                                           cfg.num_threshold, cfg.cat_threshold)
        state = "drifted" if report["prediction_drift"] else "stable"
        ctx.logger.info(f"Predictions {state} (score {report['prediction_drift_score']:.4g}, {table.iloc[0]['method']})")
        return HandlerResult(outputs=[report, table], preview=preview_dataframe(table), documents=_html(snapshot), metrics=report)


@node(
    "data_quality", label="Data Quality Report", category="monitor",
    description="Evidently data summary: missing values, duplicates, constant columns and per-column statistics, "
                "side by side with a reference table when connected",
    inputs=[Port("current", "dataset"), Port("reference", "dataset", optional=True)],
    outputs=[Port("report", "report"), Port("columns", "dataset")],
    fields={},
    code=EXPORT["data_quality"],
)
class DataQualityHandler:
    class Config(BaseModel):
        pass

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        self.Config(**ctx.config)
        _need_evidently()
        current: pd.DataFrame = ctx.inputs[0]
        reference: pd.DataFrame | None = ctx.inputs[1] if len(ctx.inputs) > 1 else None
        report, table, snapshot = _athena_data_quality(current, reference)
        ctx.logger.info(f"{int(report['rows'])} rows, {int(report['columns'])} columns, "
                        f"{report['missing_share']:.1%} missing, {int(report['duplicated_rows'])} duplicated row(s)")
        keys = ("rows", "columns", "missing_share", "duplicated_rows", "constant_columns", "empty_columns")
        return HandlerResult(outputs=[report, table], preview=preview_dataframe(table), documents=_html(snapshot),
                             metrics={k: report[k] for k in keys if k in report})
