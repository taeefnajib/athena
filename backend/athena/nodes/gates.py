"""Quality gates and fairness checks: acceptance criteria a model must meet before it's saved, registered or deployed.

The Quality Gate checks rules like ``f1 >= 0.9`` against the reports of Metrics, Fairness Check, Drift Detection...;
when they fail it stops the run (nothing downstream of it sees the model) or warns. The ``_athena_*`` helpers are
self-contained and copied verbatim into exported scripts.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.schemas.artifacts import TextPreview
from athena.sdk import Port, node, ui
from athena.utils.plotting import SERIES, fig_to_plot_preview, style_axes


def _athena_check_rules(reports, rules):
    """Check ``metric op number`` rules (one per line, # comments allowed) against merged metric reports.
    Returns a list of (rule, metric, value, passed). Raises ValueError for a bad rule or an unknown metric."""
    import math
    import operator
    import re
    ops = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": operator.eq, "!=": operator.ne}
    values = {}
    for rep in reports:
        if isinstance(rep, dict):
            values.update({str(k): float(v) for k, v in rep.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
    pattern = re.compile(r"^([A-Za-z_][\w./\[\]-]*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)$")
    results = []
    for raw in str(rules).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = pattern.match(line)
        if not m:
            raise ValueError(f"Can't read the rule {line!r}: write it like  f1 >= 0.9")
        metric, op, threshold = m.group(1), m.group(2), float(m.group(3))
        if metric not in values:
            raise ValueError(f"No input reports {metric!r}. Available: {', '.join(sorted(values)) or 'none'}")
        value = values[metric]
        passed = not math.isnan(value) and ops[op](value, threshold)
        results.append((line, metric, value, passed))
    if not results:
        raise ValueError("Write at least one rule, e.g.  f1 >= 0.9")
    return results


def _athena_fairness(model, X, y, column, positive=""):
    """Per-group selection rate, true-positive rate and accuracy for one sensitive column, and the disparities.
    Returns (report, groups) where groups is a list of dicts."""
    import numpy as np
    if column not in X.columns:
        raise ValueError(f"Sensitive column {column!r} isn't in the test features. Available: {', '.join(map(str, X.columns[:15]))}")
    groups_col = X[column]
    if groups_col.nunique() > 20:
        raise ValueError(f"{column!r} has {groups_col.nunique()} distinct values: pick a categorical column (or a one-hot column such as gender_f)")
    y_true = np.asarray(y)
    classes = list(getattr(model, "classes_", np.unique(y_true)))
    if len(classes) != 2:
        raise ValueError(f"Fairness Check needs a binary classifier; this one has {len(classes)} classes")
    pos = next((c for c in classes if str(c) == str(positive).strip()), None) if str(positive).strip() else classes[1]
    if pos is None:
        raise ValueError(f"Positive class {positive!r} isn't one of {[str(c) for c in classes]}")
    pred = np.asarray(model.predict(X)) == pos
    actual = y_true == pos
    groups = []
    for g in sorted(groups_col.dropna().unique(), key=str):
        mask = (groups_col == g).to_numpy()
        pos_mask = mask & actual
        groups.append({"group": str(g), "rows": int(mask.sum()), "selection_rate": float(pred[mask].mean()),
                       "true_positive_rate": float(pred[pos_mask].mean()) if pos_mask.any() else float("nan"),
                       "accuracy": float((pred[mask] == actual[mask]).mean())})
    sel = [g["selection_rate"] for g in groups]
    tpr = [g["true_positive_rate"] for g in groups if not np.isnan(g["true_positive_rate"])]
    report = {"groups": float(len(groups)),
              "demographic_parity_difference": float(max(sel) - min(sel)) if sel else 0.0,
              "disparate_impact_ratio": float(min(sel) / max(sel)) if sel and max(sel) > 0 else 0.0,
              "equal_opportunity_difference": float(max(tpr) - min(tpr)) if len(tpr) > 1 else 0.0}
    return report, groups


@node(
    "quality_gate", label="Quality Gate", category="deploy",
    description="Acceptance criteria (e.g. f1 >= 0.9, drifted_columns == 0): stops the run if they fail, so nothing after it sees a failing model",
    inputs=[Port("report", "report"), Port("report_2", "report", optional=True), Port("report_3", "report", optional=True),
            Port("model", "model", optional=True)],
    outputs=[Port("model", "model"), Port("report", "report")],
    fields={
        "rules": ui("Rules", widget="textarea", mono=True,
                    help="One per line: metric, then >= <= > < == or !=, then a number. Metrics come from the connected reports "
                         "(Metrics, Fairness Check, Drift Detection...). # starts a comment."),
        "on_fail": ui("When a rule fails", help="stop: fail the run here, so later nodes (save, register, deploy) don't run. warn: log and carry on."),
    },
    code=EXPORT["quality_gate"],
)
class QualityGateHandler:
    class Config(BaseModel):
        rules: str = "f1 >= 0.8"
        on_fail: Literal["stop", "warn"] = "stop"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        reports = [r for r in ctx.inputs[:3] if r is not None]
        model = ctx.inputs[3] if len(ctx.inputs) > 3 else None
        results = _athena_check_rules(reports, cfg.rules)
        lines = [f"{'✓' if ok else '✗'} {rule}   (got {value:.4g})" for rule, _, value, ok in results]
        passed = all(ok for *_, ok in results)
        for line in lines:
            (ctx.logger.info if line.startswith("✓") else ctx.logger.warning)(line)
        failed = [f"{rule} (got {value:.4g})" for rule, _, value, ok in results if not ok]
        if failed and cfg.on_fail == "stop":
            raise ValueError(f"Quality gate failed: {'; '.join(failed)}")
        report = {"passed": float(passed), "rules_passed": float(sum(ok for *_, ok in results)), "rules_total": float(len(results))}
        verdict = "PASSED" if passed else "FAILED (warn only: the run carried on)"
        return HandlerResult(outputs=[model, report], metrics=report,
                             preview=TextPreview(text=f"Quality gate {verdict}\n\n" + "\n".join(lines)))


@node(
    "fairness_check", label="Fairness Check", category="eval",
    description="Compare a classifier across groups of a sensitive column: selection rate, true-positive rate, and their disparities",
    inputs=[Port("model", "model"), Port("X_test", "X_test"), Port("y_test", "y_test")],
    outputs=[Port("report", "report")],
    fields={
        "sensitive_col": ui("Sensitive column", help="A column of the test features with groups to compare, e.g. gender or region (up to 20 groups)."),
        "positive_class": ui("Positive class", help="The favourable outcome. Empty = the second class in sorted order (e.g. 1)."),
    },
    code=EXPORT["fairness_check"],
)
class FairnessCheckHandler:
    class Config(BaseModel):
        sensitive_col: str = Field("", description="Column to group by")
        positive_class: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        if not cfg.sensitive_col.strip():
            raise ValueError("Choose the sensitive column to compare groups by")
        model, X, y = ctx.inputs
        report, groups = _athena_fairness(model, X, y, cfg.sensitive_col.strip(), cfg.positive_class)
        for g in groups:
            ctx.logger.info(f"Group {g['group']}", rows=g["rows"], selection_rate=round(g["selection_rate"], 4),
                            true_positive_rate=round(g["true_positive_rate"], 4), accuracy=round(g["accuracy"], 4))
        ctx.logger.info("Disparities", **{k: round(v, 4) for k, v in report.items() if k != "groups"})
        if report["disparate_impact_ratio"] < 0.8:
            ctx.logger.warning("Disparate impact ratio is below 0.8 (the common four-fifths rule of thumb)")
        return HandlerResult(outputs=[report], metrics=report, preview=fig_to_plot_preview(_fairness_plot(groups, cfg.sensitive_col, report)))


def _fairness_plot(groups: list[dict[str, Any]], column: str, report: dict[str, float]) -> Any:
    import matplotlib.pyplot as plt
    names = [g["group"] for g in groups]
    x = np.arange(len(names))
    w = min(0.36, 0.8 / 2)
    fig, ax = plt.subplots(figsize=(max(5.5, 1.1 * len(names) + 3), 4))
    for i, (key, label) in enumerate([("selection_rate", "Selection rate"), ("true_positive_rate", "True-positive rate")]):
        vals = [0 if np.isnan(g[key]) else g[key] for g in groups]
        ax.bar(x + (i - 0.5) * (w + 0.02), vals, width=w, color=SERIES[i], label=label)
    ax.set_xticks(x, names)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel(column)
    ax.set_title(f"By {column} · parity gap {report['demographic_parity_difference']:.3f} · impact ratio {report['disparate_impact_ratio']:.2f}",
                 fontsize=10.5, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8.5, frameon=False)
    style_axes(ax)
    fig.tight_layout()
    return fig
