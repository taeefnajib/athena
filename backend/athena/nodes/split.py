from pydantic import BaseModel
from typing import Literal
import pandas as pd
from sklearn.model_selection import train_test_split, KFold, StratifiedKFold

from athena.core.registry import register
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe, get_target_column
from athena.schemas.artifacts import TextPreview


@register("train_test")
class TrainTestHandler:
    class Config(BaseModel):
        test_size: float = 0.2
        random_state: int = 42
        stratify: bool = False
        target_col: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = cfg.target_col.strip() if cfg.target_col.strip() else get_target_column(df)

        X = df.drop(columns=[target_col])
        y = df[target_col]

        stratify_arr = y if cfg.stratify else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=cfg.test_size, random_state=cfg.random_state, stratify=stratify_arr,
        )

        ctx.logger.info("Split", train=len(X_train), test=len(X_test), features=len(X.columns))
        return HandlerResult(
            outputs=[X_train, y_train, X_test, y_test],
            preview=preview_dataframe(X_train),
            metrics={
                "train_rows": float(len(X_train)),
                "test_rows": float(len(X_test)),
                "features": float(len(X_train.columns)),
            },
        )


@register("train_val_test")
class TrainValTestHandler:
    class Config(BaseModel):
        val_size: float = 0.1
        test_size: float = 0.2
        random_state: int = 42
        target_col: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = cfg.target_col.strip() if cfg.target_col.strip() else get_target_column(df)

        X = df.drop(columns=[target_col])
        y = df[target_col]

        X_temp, X_test, y_temp, y_test = train_test_split(
            X, y, test_size=cfg.test_size, random_state=cfg.random_state,
        )
        relative_val = cfg.val_size / (1.0 - cfg.test_size)
        X_train, X_val, y_train, y_val = train_test_split(
            X_temp, y_temp, test_size=relative_val, random_state=cfg.random_state,
        )

        ctx.logger.info("Split", train=len(X_train), val=len(X_val), test=len(X_test))
        return HandlerResult(
            outputs=[X_train, y_train, X_val, y_val, X_test, y_test],
            preview=preview_dataframe(X_train),
            metrics={
                "train_rows": float(len(X_train)),
                "val_rows": float(len(X_val)),
                "test_rows": float(len(X_test)),
                "features": float(len(X_train.columns)),
            },
        )


@register("cv_split")
class CvSplitHandler:
    class Config(BaseModel):
        target_col: str = ""
        k: int = 5
        fold_index: int = 0
        method: Literal["StratifiedKFold", "KFold"] = "StratifiedKFold"
        shuffle: bool = True
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = cfg.target_col.strip() if cfg.target_col.strip() else get_target_column(df)

        X = df.drop(columns=[target_col])
        y = df[target_col]

        rng = cfg.random_state if cfg.shuffle else None
        if cfg.method == "StratifiedKFold":
            splitter: KFold | StratifiedKFold = StratifiedKFold(n_splits=cfg.k, shuffle=cfg.shuffle, random_state=rng)
            splits = list(splitter.split(X, y))
        else:
            splitter = KFold(n_splits=cfg.k, shuffle=cfg.shuffle, random_state=rng)
            splits = list(splitter.split(X))

        fold_idx = cfg.fold_index % cfg.k
        train_idx, test_idx = splits[fold_idx]

        X_train = X.iloc[train_idx].reset_index(drop=True)
        X_test  = X.iloc[test_idx].reset_index(drop=True)
        y_train = y.iloc[train_idx].reset_index(drop=True)
        y_test  = y.iloc[test_idx].reset_index(drop=True)

        ctx.logger.info(
            "CV split", method=cfg.method, k=cfg.k, fold=fold_idx,
            train=len(X_train), test=len(X_test), features=len(X.columns),
        )
        return HandlerResult(
            outputs=[X_train, y_train, X_test, y_test],
            preview=preview_dataframe(X_train),
            metrics={
                "train_rows": float(len(X_train)),
                "test_rows": float(len(X_test)),
                "features": float(len(X_train.columns)),
                "fold_index": float(fold_idx),
                "k_folds": float(cfg.k),
            },
        )


@register("dataset_to_xy")
class DatasetToXyHandler:
    class Config(BaseModel):
        target_col: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = cfg.target_col.strip() if cfg.target_col.strip() else get_target_column(df)

        if target_col not in df.columns:
            raise ValueError(f"Target column '{target_col}' not found in dataset")

        X = df.drop(columns=[target_col])
        y = df[target_col]

        ctx.logger.info("Dataset → X, y", target=target_col, features=len(X.columns), rows=len(X))
        return HandlerResult(
            outputs=[X, y],
            preview=preview_dataframe(X),
            metrics={"rows": float(len(X)), "features": float(len(X.columns))},
        )


@register("xy_to_dataset")
class XyToDatasetHandler:
    class Config(BaseModel):
        target_col: str = "target"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X: pd.DataFrame = ctx.inputs[0]
        y: pd.Series = ctx.inputs[1]

        target_name = cfg.target_col.strip() if cfg.target_col.strip() else "target"
        y_series = pd.Series(y, name=target_name)

        df = X.join(y_series, how="inner")
        ctx.logger.info("X, y → dataset", target=target_name, rows=len(df), cols=len(df.columns))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )
