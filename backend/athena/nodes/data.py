from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np
from sklearn.datasets import make_classification, make_regression

from athena.core.registry import register
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe
from athena.schemas.artifacts import TextPreview


@register("csv_loader")
class CsvLoaderHandler:
    class Config(BaseModel):
        path: str = "data.csv"
        sep: str = ","
        header: bool = True
        encoding: str = "utf-8"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        ctx.logger.info("Loading CSV", path=cfg.path)
        header_val = 0 if cfg.header else None
        sep = cfg.sep.replace("\\t", "\t")
        try:
            df = pd.read_csv(cfg.path, sep=sep, header=header_val, encoding=cfg.encoding)
        except FileNotFoundError:
            raise ValueError(f"File not found: {cfg.path}")
        ctx.logger.info("Loaded", rows=len(df), cols=len(df.columns))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@register("synth_data")
class SynthDataHandler:
    class Config(BaseModel):
        rows: int = 1000
        features: int = 10
        task: str = "classification"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        ctx.logger.info("Generating synthetic data", rows=cfg.rows, features=cfg.features, task=cfg.task)
        if cfg.task == "regression":
            X, y = make_regression(n_samples=cfg.rows, n_features=cfg.features, noise=0.1, random_state=42)
        else:
            X, y = make_classification(
                n_samples=cfg.rows, n_features=cfg.features,
                n_informative=min(cfg.features, 5), random_state=42,
            )
        df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(cfg.features)])
        df["target"] = y
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@register("excel_loader")
class ExcelLoaderHandler:
    class Config(BaseModel):
        path: str = ""
        sheet: str = "Sheet1"
        header: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        ctx.logger.info("Loading Excel", path=cfg.path)
        try:
            df = pd.read_excel(cfg.path, sheet_name=cfg.sheet, header=0 if cfg.header else None)
        except FileNotFoundError:
            raise ValueError(f"File not found: {cfg.path}")
        ctx.logger.info("Loaded", rows=len(df), cols=len(df.columns))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@register("json_loader")
class JsonLoaderHandler:
    class Config(BaseModel):
        path: str = "data.json"
        orient: Literal["records", "index", "columns", "values"] = "records"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        ctx.logger.info("Loading JSON", path=cfg.path)
        try:
            df = pd.read_json(cfg.path, orient=cfg.orient)
        except FileNotFoundError:
            raise ValueError(f"File not found: {cfg.path}")
        ctx.logger.info("Loaded", rows=len(df), cols=len(df.columns))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@register("data_merge")
class DataMergeHandler:
    class Config(BaseModel):
        on: str = "id"
        how: Literal["inner", "left", "right", "outer"] = "inner"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        left: pd.DataFrame = ctx.inputs[0]
        right: pd.DataFrame = ctx.inputs[1]
        on_cols = [c.strip() for c in cfg.on.split(",") if c.strip()]
        for col in on_cols:
            if col not in left.columns:
                raise ValueError(f"Join key '{col}' not found in left dataset")
            if col not in right.columns:
                raise ValueError(f"Join key '{col}' not found in right dataset")
        key = on_cols if len(on_cols) > 1 else on_cols[0]
        merged = pd.merge(left, right, on=key, how=cfg.how)
        ctx.logger.info("Merged", how=cfg.how, rows=len(merged))
        return HandlerResult(
            outputs=[merged],
            preview=preview_dataframe(merged),
            metrics={"rows": float(len(merged)), "cols": float(len(merged.columns))},
        )


@register("data_sample")
class DataSampleHandler:
    class Config(BaseModel):
        n: int = 500
        frac: float = 0.0
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        if cfg.frac > 0:
            result = df.sample(frac=min(cfg.frac, 1.0), random_state=cfg.random_state)
        else:
            result = df.sample(n=min(cfg.n, len(df)), random_state=cfg.random_state)
        ctx.logger.info("Sampled", rows=len(result))
        return HandlerResult(
            outputs=[result],
            preview=preview_dataframe(result),
            metrics={"rows": float(len(result)), "cols": float(len(result.columns))},
        )


@register("manual_input")
class ManualInputHandler:
    class Config(BaseModel):
        columns: str = ""
        data: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        cols = [c.strip() for c in cfg.columns.split(",") if c.strip()]
        if not cols:
            raise ValueError("No column names specified. Fill in the Columns field.")

        lines = [ln.strip() for ln in cfg.data.strip().splitlines() if ln.strip()]
        if not lines:
            raise ValueError("No data rows provided. Fill in the Data Rows field.")

        rows: list[list[str]] = []
        for i, line in enumerate(lines, 1):
            vals = [v.strip() for v in line.split(",")]
            if len(vals) != len(cols):
                raise ValueError(
                    f"Row {i} has {len(vals)} value(s) but {len(cols)} column(s) are defined."
                )
            rows.append(vals)

        df = pd.DataFrame(rows, columns=cols)
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass

        ctx.logger.info("Manual input created", rows=len(df), cols=len(df.columns))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


def _stub(type_name: str, msg: str = ""):
    @register(type_name)
    class StubHandler:
        def __call__(self, ctx: ExecutionContext) -> HandlerResult:
            raise NotImplementedError(msg or f"{type_name} is not yet implemented.")
    StubHandler.__name__ = f"{type_name.title().replace('_', '')}Handler"


_stub("db_connector", "db_connector requires a live database — export the pipeline and use SQLAlchemy manually.")
_stub("api_fetch",   "api_fetch makes external HTTP calls — export the pipeline and call the API manually.")
