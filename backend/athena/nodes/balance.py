from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np

from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe, get_target_column


@node(
    "smote", label="SMOTE", category="balance",
    description="Oversample minority class synthetically",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "k_neighbors": ui("K Neighbors"),
        "random_state": ui("Random Seed"),
    },
    export_note="Not exportable yet: no code template for this node.",
)
class SmoteHandler:
    class Config(BaseModel):
        k_neighbors: int = 5
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = get_target_column(df)
        X = df.drop(columns=[target_col])
        y = df[target_col]

        try:
            from imblearn.over_sampling import SMOTE
        except ImportError:
            raise ImportError("imbalanced-learn is required: pip install imbalanced-learn")

        sm = SMOTE(k_neighbors=cfg.k_neighbors, random_state=cfg.random_state)
        X_res, y_res = sm.fit_resample(X, y)
        result = pd.DataFrame(X_res, columns=X.columns)
        result[target_col] = y_res
        ctx.logger.info("SMOTE resampled", before=len(df), after=len(result))
        return HandlerResult(
            outputs=[result],
            preview=preview_dataframe(result),
            metrics={"before": float(len(df)), "after": float(len(result))},
        )


@node(
    "undersample", label="Undersampling", category="balance",
    description="Reduce majority class samples",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "strategy": ui(),
        "ratio": ui(),
    },
    export_note="Not exportable yet: no code template for this node.",
)
class UndersampleHandler:
    class Config(BaseModel):
        strategy: Literal["random", "tomek", "enn"] = "random"
        ratio: float = 1.0

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = get_target_column(df)
        X = df.drop(columns=[target_col]).values
        y = df[target_col].values

        try:
            from imblearn.under_sampling import RandomUnderSampler, TomekLinks, EditedNearestNeighbours
        except ImportError:
            raise ImportError("imbalanced-learn is required: pip install imbalanced-learn")

        if cfg.strategy == "tomek":
            sampler = TomekLinks()
        elif cfg.strategy == "enn":
            sampler = EditedNearestNeighbours()
        else:
            sampler = RandomUnderSampler(sampling_strategy=cfg.ratio, random_state=42)

        X_res, y_res = sampler.fit_resample(X, y)
        feature_cols = [c for c in df.columns if c != target_col]
        result = pd.DataFrame(X_res, columns=feature_cols)
        result[target_col] = y_res
        ctx.logger.info("Undersampled", before=len(df), after=len(result))
        return HandlerResult(
            outputs=[result],
            preview=preview_dataframe(result),
            metrics={"before": float(len(df)), "after": float(len(result))},
        )


@node(
    "oversample", label="Oversampling", category="balance",
    description="Duplicate minority class samples",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "strategy": ui(),
    },
    export_note="Not exportable yet: no code template for this node.",
)
class OversampleHandler:
    class Config(BaseModel):
        strategy: Literal["random", "adasyn"] = "random"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = get_target_column(df)
        X = df.drop(columns=[target_col]).values
        y = df[target_col].values

        try:
            from imblearn.over_sampling import RandomOverSampler, ADASYN
        except ImportError:
            raise ImportError("imbalanced-learn is required: pip install imbalanced-learn")

        sampler = ADASYN(random_state=42) if cfg.strategy == "adasyn" else RandomOverSampler(random_state=42)
        X_res, y_res = sampler.fit_resample(X, y)
        feature_cols = [c for c in df.columns if c != target_col]
        result = pd.DataFrame(X_res, columns=feature_cols)
        result[target_col] = y_res
        ctx.logger.info("Oversampled", before=len(df), after=len(result))
        return HandlerResult(
            outputs=[result],
            preview=preview_dataframe(result),
            metrics={"before": float(len(df)), "after": float(len(result))},
        )


@node(
    "class_weight", label="Class Weight Adjuster", category="balance",
    description="Balance via class weights",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "mode": ui(),
    },
    export_note="Not exportable yet: no code template for this node.",
)
class ClassWeightHandler:
    class Config(BaseModel):
        mode: Literal["balanced", "auto", "custom"] = "balanced"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = get_target_column(df)
        y = df[target_col]

        from sklearn.utils.class_weight import compute_class_weight
        classes = np.unique(y)
        weights = compute_class_weight("balanced", classes=classes, y=y)
        weight_map = dict(zip(classes.tolist(), weights.tolist()))
        ctx.logger.info("Class weights computed", weights=weight_map)
        from athena.schemas.artifacts import TextPreview
        text = "Class weights:\n" + "\n".join(f"  {cls}: {w:.4f}" for cls, w in weight_map.items())
        return HandlerResult(
            outputs=[df],
            preview=TextPreview(text=text),
            metrics={str(k): float(v) for k, v in weight_map.items()},
        )
