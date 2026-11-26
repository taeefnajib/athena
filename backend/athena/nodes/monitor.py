from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np

from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.schemas.artifacts import TextPreview, MetricsPreview
from athena.utils.dataframes import get_target_column


@node(
    "drift_detect", label="Drift Detection", category="monitor",
    description="Detect feature and concept drift",
    inputs=[Port("dataset", "dataset"), Port("reference", "dataset")],
    outputs=[Port("report", "report")],
    fields={
        "method": ui(),
        "threshold": ui(),
    },
    export_note="Not exportable yet: no code template for this node.",
)
class DriftDetectHandler:
    class Config(BaseModel):
        method: Literal["PSI", "KS Test", "Chi-squared"] = "KS Test"
        threshold: float = 0.05

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        current: pd.DataFrame = ctx.inputs[0]
        reference: pd.DataFrame = ctx.inputs[1]

        num_cols = [c for c in current.columns if c in reference.columns
                    and pd.api.types.is_numeric_dtype(current[c])]

        drift_scores: dict[str, float] = {}
        drifted: list[str] = []

        for col in num_cols:
            cur = current[col].dropna().values
            ref = reference[col].dropna().values
            if len(cur) == 0 or len(ref) == 0:
                continue

            if cfg.method == "PSI":
                # Population Stability Index
                breakpoints = np.percentile(ref, np.linspace(0, 100, 11))
                breakpoints = np.unique(breakpoints)
                exp = np.histogram(ref, bins=breakpoints)[0].astype(float) + 1e-6
                act = np.histogram(cur, bins=breakpoints)[0].astype(float) + 1e-6
                exp /= exp.sum(); act /= act.sum()
                score = float(np.sum((act - exp) * np.log(act / exp)))
                drift_scores[col] = score
                if score > 0.2:
                    drifted.append(col)
            else:
                # KS Test — compute statistic manually (max CDF diff)
                combined = np.concatenate([ref, cur])
                combined.sort()
                cdf_ref = np.searchsorted(np.sort(ref), combined, side="right") / len(ref)
                cdf_cur = np.searchsorted(np.sort(cur), combined, side="right") / len(cur)
                ks_stat = float(np.max(np.abs(cdf_ref - cdf_cur)))
                drift_scores[col] = ks_stat
                if ks_stat > cfg.threshold:
                    drifted.append(col)

        summary = (
            f"Drift Detection ({cfg.method})\n"
            f"Columns checked: {len(drift_scores)}\n"
            f"Drifted columns: {len(drifted)}\n"
            + ("\nDrifted:\n" + "\n".join(f"  {c}: {drift_scores[c]:.4f}" for c in drifted) if drifted else "\nNo significant drift detected.")
        )
        report = {"drifted_columns": len(drifted), "columns_checked": len(drift_scores), **drift_scores}
        ctx.logger.info("Drift detection done", drifted=len(drifted), checked=len(drift_scores))
        return HandlerResult(
            outputs=[report],
            preview=TextPreview(text=summary),
            metrics={"drifted_columns": float(len(drifted)), "columns_checked": float(len(drift_scores))},
        )


@node(
    "perf_tracker", label="Performance Tracker", category="monitor",
    description="Track model performance over time",
    inputs=[Port("model", "model"), Port("dataset", "dataset")],
    outputs=[Port("report", "report")],
    fields={
        "metric": ui(),
        "window": ui("Window (days)"),
    },
    export_note="Not exportable yet: no code template for this node.",
)
class PerfTrackerHandler:
    class Config(BaseModel):
        metric: Literal["accuracy", "f1", "rmse"] = "accuracy"
        window: int = 7

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        df: pd.DataFrame = ctx.inputs[1]
        target_col = get_target_column(df)
        X = df.drop(columns=[target_col])
        y = df[target_col]
        y_pred = model.predict(X)

        result_metrics: dict[str, float] = {}
        if cfg.metric == "accuracy":
            from sklearn.metrics import accuracy_score
            result_metrics["accuracy"] = float(accuracy_score(y, y_pred))
        elif cfg.metric == "f1":
            from sklearn.metrics import f1_score
            result_metrics["f1"] = float(f1_score(y, y_pred, average="weighted", zero_division=0))
        else:
            from sklearn.metrics import mean_squared_error
            result_metrics["rmse"] = float(np.sqrt(mean_squared_error(y, y_pred)))

        result_metrics["samples"] = float(len(y))
        ctx.logger.info("Performance tracked", metric=cfg.metric, value=list(result_metrics.values())[0])
        return HandlerResult(
            outputs=[result_metrics],
            preview=MetricsPreview(values=result_metrics),
            metrics=result_metrics,
        )
