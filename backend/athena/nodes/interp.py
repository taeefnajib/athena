from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.plotting import fig_to_plot_preview
from athena.schemas.artifacts import TextPreview


@node(
    "shap", label="SHAP Explainer", category="interp",
    description="SHAP-based model explanations",
    inputs=[Port("model", "model"), Port("X_test", "X_test")],
    outputs=[Port("report", "report")],
    fields={
        "plot": ui("Plot Type"),
        "n_samples": ui("Samples"),
    },
    code=EXPORT["shap"],
)
class ShapHandler:
    class Config(BaseModel):
        plot: Literal["summary", "bar", "waterfall", "beeswarm"] = "summary"
        n_samples: int = 100

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        X_test: pd.DataFrame = ctx.inputs[1]

        try:
            import shap
        except ImportError:
            raise ImportError("shap is required: pip install shap")

        import matplotlib.pyplot as plt
        matplotlib_backend = plt.get_backend()

        sample = X_test.head(cfg.n_samples)

        # Choose explainer based on model type
        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(sample)
        except Exception:
            try:
                explainer = shap.LinearExplainer(model, sample)
                shap_values = explainer.shap_values(sample)
            except Exception:
                explainer = shap.KernelExplainer(model.predict, shap.sample(sample, 50))
                shap_values = explainer.shap_values(sample, nsamples=50)

        # Take first class shap values if multiclass
        sv = shap_values[0] if isinstance(shap_values, list) else shap_values

        plt.switch_backend("Agg")
        fig, ax = plt.subplots(figsize=(8, 5))
        shap.summary_plot(sv, sample, plot_type="bar" if cfg.plot == "bar" else "dot",
                          show=False, max_display=20)
        plt.tight_layout()

        preview = fig_to_plot_preview(plt.gcf())
        plt.close("all")
        ctx.logger.info("SHAP explanation computed", samples=len(sample))
        return HandlerResult(outputs=[preview], preview=preview)


@node(
    "debugger", label="Model Debugger", category="interp",
    description="Diagnose model issues and errors",
    inputs=[Port("model", "model"), Port("X_test", "X_test"), Port("y_test", "y_test")],
    outputs=[Port("report", "report")],
    code=EXPORT["debugger"],
)
class DebuggerHandler:
    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        model = ctx.inputs[0]
        X_test: pd.DataFrame = ctx.inputs[1]
        y_test: pd.Series = ctx.inputs[2]

        y_pred = model.predict(X_test)
        errors = np.abs(np.array(y_test) - np.array(y_pred))
        worst_idx = np.argsort(errors)[-10:]

        lines = [
            f"Model: {type(model).__name__}",
            f"Test samples: {len(y_test)}",
            f"Features: {X_test.shape[1]}",
            "",
            "10 worst predictions:",
        ]
        for i in worst_idx[::-1]:
            lines.append(f"  idx={i}  true={y_test.iloc[i]!r}  pred={y_pred[i]!r}  err={errors[i]:.4f}")

        if hasattr(model, "feature_importances_"):
            names = getattr(model, "feature_names_in_", X_test.columns)
            top = np.argsort(model.feature_importances_)[-5:][::-1]
            lines += ["", "Top 5 features by importance:"]
            for i in top:
                lines.append(f"  {names[i]}: {model.feature_importances_[i]:.4f}")

        report = {"worst_errors": errors[worst_idx].tolist(), "mean_error": float(errors.mean())}
        ctx.logger.info("Debugger analysis done", mean_error=float(errors.mean()))
        return HandlerResult(
            outputs=[report],
            preview=TextPreview(text="\n".join(lines)),
            metrics={"mean_error": float(errors.mean()), "max_error": float(errors.max())},
        )


@node(
    "lime", label="LIME Explainer", category="interp",
    description="Local interpretable explanations",
    inputs=[Port("model", "model"), Port("X_test", "X_test")],
    outputs=[Port("report", "report")],
    fields={
        "n_features": ui("Top Features", widget="number"),
        "mode": ui(widget="select", options=["classification", "regression"]),
    },
    export_note="Not implemented yet.",
    available=False, unavailable_reason="Not implemented yet (roadmap phase 1).",
)
class LimeHandler:
    class Config(BaseModel):
        n_features: int = 10
        mode: str = 'classification'

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        raise NotImplementedError("Not implemented yet (roadmap phase 1).")

