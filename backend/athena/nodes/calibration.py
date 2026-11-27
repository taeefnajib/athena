"""Probability calibration, calibration curves and decision-threshold tuning for classifiers.

Calibration and threshold tuning both need data the model wasn't fitted on. When X_val / y_val are connected
they use the validation set; otherwise they use out-of-fold predictions from k-fold cross-validation on the
training set. The test set is never used for tuning: evaluate the result on it downstream.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.schemas.artifacts import ModelPreview
from athena.sdk import Port, node, ui
from athena.utils.plotting import SERIES, fig_to_plot_preview, style_axes

Objective = Literal["f1", "balanced_accuracy", "max_recall_at_precision", "max_precision_at_recall", "min_cost"]


# ---- helpers copied verbatim into exported scripts (keep them self-contained) -------------------------

def _athena_tuning_scores(model, X_train, y_train, X_val=None, y_val=None, cv=5, positive=""):
    """Probabilities the model didn't see while fitting: on the validation set if given, else out-of-fold
    predictions from stratified k-fold cross-validation on the training set. Returns (scores, y, labels)."""
    import numpy as np
    from sklearn.base import clone
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    if not hasattr(model, "predict_proba"):
        raise ValueError(f"{type(model).__name__} doesn't output probabilities (no predict_proba)")
    classes = list(getattr(model, "classes_", np.unique(y_train)))
    if len(classes) != 2:
        raise ValueError(f"Needs a binary target; this one has {len(classes)} classes")
    pos = next((c for c in classes if str(c) == str(positive).strip()), None) if str(positive).strip() else classes[1]
    if pos is None:
        raise ValueError(f"Positive class {positive!r} isn't one of the classes {[str(c) for c in classes]}")
    col = classes.index(pos)
    if X_val is not None and y_val is not None:
        scores, y = model.predict_proba(X_val)[:, col], np.asarray(y_val)
    else:
        folds = StratifiedKFold(n_splits=int(cv), shuffle=True, random_state=0)
        scores = cross_val_predict(clone(model), X_train, y_train, cv=folds, method="predict_proba")[:, col]
        y = np.asarray(y_train)
    return scores, (y == pos), pos


def _athena_threshold(scores, is_pos, objective="f1", constraint=0.8, cost_fp=1.0, cost_fn=5.0):
    """The decision threshold that best meets the objective on (scores, is_pos). Returns (threshold, table),
    where table holds precision/recall/f1/balanced accuracy/cost for every candidate threshold."""
    import numpy as np
    s, p = np.asarray(scores, dtype=float), np.asarray(is_pos, dtype=bool)
    cand = np.unique(np.round(np.concatenate([np.linspace(0.01, 0.99, 99), np.quantile(s, np.linspace(0, 1, 201))]), 6))
    cand = cand[(cand > 0) & (cand < 1)]
    pred = s[None, :] >= cand[:, None]
    tp = (pred & p).sum(1); fp = (pred & ~p).sum(1); fn = (~pred & p).sum(1); tn = (~pred & ~p).sum(1)
    precision = tp / np.maximum(tp + fp, 1)  # 0 when nothing is predicted positive: catching nothing isn't precise
    recall = tp / max(int(p.sum()), 1)
    f1 = np.where(precision + recall > 0, 2 * precision * recall / np.maximum(precision + recall, 1e-12), 0.0)
    bal = (recall + tn / max(int((~p).sum()), 1)) / 2
    cost = fp * float(cost_fp) + fn * float(cost_fn)
    table = {"threshold": cand, "predicted_positive": tp + fp, "precision": precision, "recall": recall, "f1": f1, "balanced_accuracy": bal, "cost": cost}
    if objective in ("f1", "balanced_accuracy", "min_cost"):
        value = {"f1": f1, "balanced_accuracy": bal, "min_cost": -cost}[objective]
        ok = np.ones(len(cand), dtype=bool)
    else:
        need, value, name = ((precision, recall, "precision") if objective == "max_recall_at_precision" else (recall, precision, "recall"))
        ok = need >= float(constraint)
        if not ok.any():
            raise ValueError(f"No threshold reaches {name} {constraint:g} on the tuning data (best is {need.max():.3f}); lower the target")
    tied = np.flatnonzero(ok & np.isclose(value, value[ok].max()))
    best = int(tied[len(tied) // 2])  # thresholds that score the same: take the middle of the range, not its edge
    return float(cand[best]), table


# ---- shared node helpers -------------------------------------------------------------------------------

def _optional(ctx: ExecutionContext, i: int) -> Any:
    return ctx.inputs[i] if len(ctx.inputs) > i else None


def _source(X_val: Any, y_val: Any, cv: int) -> str:
    return "the validation set" if X_val is not None and y_val is not None else f"{cv}-fold cross-validation on the training set"


TRAIN_PORTS = [Port("model", "model"), Port("X_train", "X_train"), Port("y_train", "y_train"),
               Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True)]


# ---- nodes ---------------------------------------------------------------------------------------------

@node(
    "calibrate", label="Probability Calibration", category="advanced",
    description="Make predicted probabilities match observed frequencies (Platt sigmoid or isotonic)",
    inputs=TRAIN_PORTS, outputs=[Port("model", "model")],
    fields={
        "method": ui("Method", help="Sigmoid suits small data and most models; isotonic is more flexible but needs ~1,000+ rows."),
        "cv": ui("Folds (without a validation set)"),
    },
    code=EXPORT["calibrate"],
)
class CalibrateHandler:
    class Config(BaseModel):
        method: Literal["sigmoid", "isotonic"] = "sigmoid"
        cv: int = Field(5, ge=2, le=20)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.base import clone
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.frozen import FrozenEstimator
        from sklearn.model_selection import StratifiedKFold

        cfg = self.Config(**ctx.config)
        model, X_train, y_train = ctx.inputs[0], ctx.inputs[1], ctx.inputs[2]
        X_val, y_val = _optional(ctx, 3), _optional(ctx, 4)
        if not hasattr(model, "predict_proba"):
            raise ValueError(f"{type(model).__name__} doesn't output probabilities (no predict_proba), so there is nothing to calibrate")
        source = _source(X_val, y_val, cfg.cv)
        if X_val is not None and y_val is not None:
            calibrated = CalibratedClassifierCV(FrozenEstimator(model), method=cfg.method).fit(X_val, y_val)
            n = len(y_val)
        else:
            folds = StratifiedKFold(n_splits=cfg.cv, shuffle=True, random_state=0)
            calibrated = CalibratedClassifierCV(clone(model), method=cfg.method, cv=folds).fit(X_train, y_train)
            n = len(y_train)
        if cfg.method == "isotonic" and n < 1000:
            ctx.logger.warning(f"Isotonic calibration on {n} rows can overfit; sigmoid is usually safer below ~1,000 rows")
        ctx.logger.info("Calibrated", method=cfg.method, data=source, rows=n)
        ctx.logger.info("Check the result with a Calibration Curve node on the test set")
        return HandlerResult(
            outputs=[calibrated],
            preview=ModelPreview(summary=f"{type(model).__name__} calibrated with {cfg.method} on {source} ({n:,} rows)"),
        )


@node(
    "calibration_curve", label="Calibration Curve", category="eval",
    description="Reliability diagram: do predicted probabilities match how often the class occurs?",
    inputs=[Port("model", "model"), Port("X_test", "X_test"), Port("y_test", "y_test")],
    outputs=[Port("plot", "plot")],
    fields={"n_bins": ui("Bins"), "strategy": ui("Binning", help="Quantile bins hold equal numbers of rows; uniform bins are equal widths."),
            "positive_class": ui("Positive class", help="Empty = the second class in sorted order (e.g. 1).")},
    code=EXPORT["calibration_curve"],
)
class CalibrationCurveHandler:
    class Config(BaseModel):
        n_bins: int = Field(10, ge=3, le=50)
        strategy: Literal["uniform", "quantile"] = "uniform"
        positive_class: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import matplotlib.pyplot as plt
        from sklearn.calibration import calibration_curve
        from sklearn.metrics import brier_score_loss

        cfg = self.Config(**ctx.config)
        model, X_test, y_test = ctx.inputs
        scores, is_pos, pos = _athena_tuning_scores(model, None, y_test, X_test, y_test, positive=cfg.positive_class)
        frac, mean_pred = calibration_curve(is_pos, scores, n_bins=cfg.n_bins, strategy=cfg.strategy)
        brier = float(brier_score_loss(is_pos, scores))
        counts, edges = np.histogram(scores, bins=np.linspace(0, 1, cfg.n_bins + 1))
        bins = np.clip(np.digitize(scores, edges[1:-1]), 0, cfg.n_bins - 1)
        ece = float(sum(abs(is_pos[bins == b].mean() - scores[bins == b].mean()) * (bins == b).mean()
                        for b in range(cfg.n_bins) if (bins == b).any()))
        fig, (ax, axh) = plt.subplots(2, 1, figsize=(6, 6), height_ratios=[3, 1], sharex=True)
        ax.plot([0, 1], [0, 1], color="#999999", lw=1, linestyle=(0, (4, 3)))
        ax.text(0.98, 0.03, "dashed line = perfectly calibrated", color="#666666", fontsize=8, ha="right")
        ax.plot(mean_pred, frac, color=SERIES[0], lw=2, marker="o", markersize=5, markeredgecolor="white", markeredgewidth=1.5)
        ax.set_ylabel(f"Observed share of {pos}")
        ax.set_title(f"Calibration curve · Brier {brier:.3f} · ECE {ece:.3f}", fontsize=11, loc="left")
        ax.set_ylim(0, 1)
        axh.bar(edges[:-1], counts, width=np.diff(edges) - 0.004, align="edge", color=SERIES[0], alpha=0.35)
        axh.set_xlabel("Predicted probability"); axh.set_ylabel("Rows")
        axh.set_xlim(0, 1)
        style_axes(ax); style_axes(axh)
        fig.tight_layout()
        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Calibration curve plotted", brier=round(brier, 4), ece=round(ece, 4))
        return HandlerResult(outputs=[preview], preview=preview, metrics={"brier": brier, "ece": ece})


@node(
    "threshold_tune", label="Decision Threshold", category="advanced",
    description="Pick the probability cut-off for a binary classifier by F1, balanced accuracy, a precision or recall target, or error costs",
    inputs=TRAIN_PORTS, outputs=[Port("model", "model"), Port("report", "report")],
    fields={
        "objective": ui("Objective", help="f1 / balanced_accuracy: the best score. max_recall_at_precision / max_precision_at_recall: "
                                          "the most of one while keeping the other at the minimum below. min_cost: the fewest weighted errors."),
        "constraint": ui("Minimum precision / recall", help="Used by the two 'at a minimum' objectives."),
        "cost_fp": ui("Cost of a false positive", help="Used by 'Lowest error cost'."),
        "cost_fn": ui("Cost of a false negative", help="Used by 'Lowest error cost'."),
        "positive_class": ui("Positive class", help="Empty = the second class in sorted order (e.g. 1)."),
        "cv": ui("Folds (without a validation set)"),
    },
    code=EXPORT["threshold_tune"],
)
class ThresholdTuneHandler:
    class Config(BaseModel):
        objective: Objective = "f1"
        constraint: float = Field(0.8, gt=0, le=1)
        cost_fp: float = Field(1.0, ge=0)
        cost_fn: float = Field(5.0, ge=0)
        positive_class: str = ""
        cv: int = Field(5, ge=2, le=20)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.frozen import FrozenEstimator
        from sklearn.model_selection import FixedThresholdClassifier

        cfg = self.Config(**ctx.config)
        model, X_train, y_train = ctx.inputs[0], ctx.inputs[1], ctx.inputs[2]
        X_val, y_val = _optional(ctx, 3), _optional(ctx, 4)
        scores, is_pos, pos = _athena_tuning_scores(model, X_train, y_train, X_val, y_val, cfg.cv, cfg.positive_class)
        threshold, table = _athena_threshold(scores, is_pos, cfg.objective, cfg.constraint, cfg.cost_fp, cfg.cost_fn)
        tuned = FixedThresholdClassifier(FrozenEstimator(model), threshold=threshold, pos_label=pos,
                                         response_method="predict_proba").fit(X_train, y_train)
        report = _report(table, threshold)
        source = _source(X_val, y_val, cfg.cv)
        ctx.logger.info("Threshold chosen", threshold=round(threshold, 4), objective=cfg.objective, data=source, positive=str(pos))
        return HandlerResult(outputs=[tuned, report], preview=fig_to_plot_preview(_threshold_plot(table, threshold, cfg, pos, source)),
                             metrics=report)


def _report(table: dict[str, np.ndarray], threshold: float) -> dict[str, float]:
    """Scores at the chosen threshold and at the default 0.5, on the tuning data."""
    def at(t: float) -> int:
        return int(np.argmin(np.abs(table["threshold"] - t)))
    i, d = at(threshold), at(0.5)
    out = {"threshold": threshold}
    for k in ("precision", "recall", "f1", "balanced_accuracy", "cost"):
        out[k] = float(table[k][i])
        out[f"{k}_at_0.5"] = float(table[k][d])
    return out


def _threshold_plot(table: dict[str, np.ndarray], threshold: float, cfg: Any, pos: Any, source: str) -> Any:
    import matplotlib.pyplot as plt
    t = table["threshold"]
    fig, ax = plt.subplots(figsize=(7, 4.4))
    ax.axvline(0.5, color="#bbbbbb", lw=1, linestyle=(0, (4, 3)), label="Default 0.5")
    ax.axvline(threshold, color="#191919", lw=1, label=f"Chosen {threshold:.3f}")
    some = table["predicted_positive"] > 0  # precision is undefined where nothing is predicted positive
    for (key, label), color in zip([("precision", "Precision"), ("recall", "Recall"), ("f1", "F1")], SERIES):
        y = np.where(some, table[key], np.nan) if key == "precision" else table[key]
        ax.plot(t, y, color=color, lw=2, label=label, solid_capstyle="round")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.02)
    ax.set_xlabel(f"Threshold on P({pos})"); ax.set_ylabel("Score")
    ax.set_title(f"Decision threshold · tuned on {source}", fontsize=11, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8.5, frameon=False)
    style_axes(ax)
    fig.tight_layout()
    return fig

