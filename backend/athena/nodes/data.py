from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np
from sklearn.datasets import make_classification, make_regression

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe
from athena.schemas.artifacts import TextPreview


@node(
    "csv_loader", label="CSV Loader", category="data",
    description="Load data from a CSV file",
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("File Path", widget="file", accept=".csv,.tsv,.txt,text/csv"),
        "sep": ui("Separator", widget="select", options=[",", ";", "\\t", "|"]),
        "header": ui("Header Row"),
        "encoding": ui(widget="select", options=["utf-8", "latin-1", "utf-16"]),
    },
    code=EXPORT["csv_loader"],
)
class CsvLoaderHandler:
    class Config(BaseModel):
        path: str = ""
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


@node(
    "synth_data", label="Synthetic Data", category="data",
    description="Generate synthetic training data",
    outputs=[Port("dataset", "dataset")],
    fields={
        "rows": ui(),
        "features": ui(),
        "task": ui("Task Type", widget="select", options=["classification", "regression", "clustering"]),
    },
    code=EXPORT["synth_data"],
)
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
                n_informative=min(cfg.features, 5),
                n_redundant=max(0, min(2, cfg.features - min(cfg.features, 5))),  # informative + redundant <= features
                random_state=42,
            )
        df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(cfg.features)])
        df["target"] = y
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@node(
    "excel_loader", label="Excel Loader", category="data",
    description="Load data from an Excel file",
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("File Path", widget="file", accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "sheet": ui("Sheet Name"),
        "header": ui("Header Row"),
    },
    code=EXPORT["excel_loader"],
)
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


@node(
    "json_loader", label="JSON Loader", category="data",
    description="Load structured JSON data",
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("File Path"),
        "orient": ui("Orientation"),
    },
    code=EXPORT["json_loader"],
)
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


@node(
    "data_merge", label="Data Merge / Join", category="data",
    description="Merge two datasets on a key column",
    inputs=[Port("left", "dataset"), Port("right", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "on": ui("Join Key"),
        "how": ui("Join Type"),
    },
    code=EXPORT["data_merge"],
)
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


@node(
    "data_sample", label="Data Sampling", category="data",
    description="Sample rows from dataset",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "n": ui("Sample Size"),
        "frac": ui("Fraction"),
        "random_state": ui("Random Seed"),
    },
    code=EXPORT["data_sample"],
)
class DataSampleHandler:
    class Config(BaseModel):
        n: int = 500
        frac: float = 0.1
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
            replay={"kind": "skip"},  # sampling rows only applies to training data
        )


@node(
    "manual_input", label="Manual Data Input", category="data",
    description="Type one or more records by hand — feed into scalers, encoders, and models for prediction",
    outputs=[Port("dataset", "dataset")],
    fields={
        "columns": ui("Column Names (comma-separated)"),
        "data": ui("Data Rows (one row per line, comma-separated values)", widget="textarea"),
    },
    code=EXPORT["manual_input"],
)
class ManualInputHandler:
    class Config(BaseModel):
        columns: str = "feature1, feature2"
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


@node(
    "db_connector", reusable=False, label="SQL Query", category="data",
    description="Run a SQL query against a saved database connection",
    outputs=[Port("dataset", "dataset")],
    fields={
        "connection": ui("Connection", widget="connection", connector="sql"),
        "query": ui("SQL Query", widget="code", language="sql"),
        "limit": ui("Row limit", help="0 = no limit"),
    },
    code=EXPORT["db_connector"],
)
class DbConnectorHandler:
    class Config(BaseModel):
        connection: str = ""
        query: str = "SELECT * FROM my_table"
        limit: int = 0

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.connectors.store import resolve_connection
        cfg = self.Config(**ctx.config)
        if not cfg.connection:
            raise ValueError("Choose a connection (create one under Connections in the top bar)")
        if not cfg.query.strip():
            raise ValueError("Enter a SQL query")
        impl, conn_cfg = resolve_connection(cfg.connection)
        ctx.logger.info("Running query", connection=cfg.connection, limit=cfg.limit or "none")
        df = impl.read(conn_cfg, cfg.query, limit=cfg.limit or None)
        ctx.logger.info("Query returned", rows=len(df), cols=len(df.columns))
        return HandlerResult(outputs=[df], preview=preview_dataframe(df), metrics={"rows": float(len(df))})

