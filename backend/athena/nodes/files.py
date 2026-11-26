"""Columnar files and SQL transforms: Parquet Loader and SQL Transform (DuckDB)."""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe


def _cols(text: str) -> list[str] | None:
    cols = [c.strip() for c in text.split(",") if c.strip()]
    return cols or None


@node(
    "parquet_loader", label="Parquet Loader", category="data",
    description="Load a Parquet file, or a folder of Parquet files (a partitioned dataset)",
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("File or folder", widget="file", accept=".parquet,.pq"),
        "columns": ui("Columns", help="Comma-separated; empty = all. Reading fewer columns is much faster."),
        "limit": ui("Row limit", min=0, help="0 = all rows"),
    },
    code=EXPORT["parquet_loader"],
)
class ParquetLoader:
    class Config(BaseModel):
        path: str = ""
        columns: str = ""
        limit: int = Field(0, ge=0)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        if not cfg.path.strip():
            raise ValueError("Enter the path of a Parquet file or folder")
        ctx.logger.info("Loading Parquet", path=cfg.path)
        try:
            df = pd.read_parquet(cfg.path, columns=_cols(cfg.columns))
        except FileNotFoundError:
            raise ValueError(f"File not found: {cfg.path}") from None
        except Exception as exc:
            raise ValueError(f"Couldn't read {cfg.path} as Parquet: {str(exc).splitlines()[0]}") from exc
        if cfg.limit:
            df = df.head(cfg.limit)
        ctx.logger.info("Loaded", rows=len(df), cols=len(df.columns))
        return HandlerResult(outputs=[df], preview=preview_dataframe(df),
                             metrics={"rows": float(len(df)), "cols": float(len(df.columns))})


@node(
    "duckdb_sql", label="SQL Transform", category="data",
    description="Transform data with SQL (DuckDB): filter, join, aggregate, window functions. Inputs are tables in1 and in2.",
    inputs=[Port("in1", "dataset"), Port("in2", "dataset", optional=True)],
    outputs=[Port("dataset", "dataset")],
    fields={
        "query": ui("SQL", widget="textarea", mono=True,
                    help="Connected inputs are tables in1 and in2. You can also read files directly: "
                         "SELECT * FROM 'data/*.parquet' or read_csv('file.csv')."),
    },
    code=EXPORT["duckdb_sql"],
)
class DuckDbSql:
    class Config(BaseModel):
        query: str = "SELECT * FROM in1 LIMIT 1000"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import duckdb

        cfg = self.Config(**ctx.config)
        if not cfg.query.strip():
            raise ValueError("Enter a SQL query")
        con = duckdb.connect()  # in-memory, private to this node
        try:
            for name, df in zip(("in1", "in2"), ctx.inputs):
                if df is not None:
                    con.register(name, df)
            ctx.logger.info("Running SQL", tables=", ".join(n for n, d in zip(("in1", "in2"), ctx.inputs) if d is not None) or "none")
            try:
                out = con.execute(cfg.query).df()
            except duckdb.Error as exc:
                raise ValueError(f"SQL error: {str(exc).splitlines()[0]}") from exc
        finally:
            con.close()
        ctx.logger.info("Query returned", rows=len(out), cols=len(out.columns))
        return HandlerResult(outputs=[out], preview=preview_dataframe(out),
                             metrics={"rows": float(len(out)), "cols": float(len(out.columns))})


@node(
    "storage_loader", label="Cloud File Loader", category="data",
    description="Load a CSV, Parquet, JSON or Excel file from S3, GCS, Azure or a folder, using a saved storage connection",
    outputs=[Port("dataset", "dataset")],
    fields={
        "connection": ui("Connection", widget="connection", connector="storage"),
        "path": ui("Path", help="Relative to the connection's bucket and prefix, e.g. sales/2026/*.parquet or customers.csv"),
        "format": ui("Format", help="auto: from the file extension (a folder is read as Parquet)"),
        "limit": ui("Row limit", min=0, help="0 = all rows"),
    },
    code=EXPORT["storage_loader"],
)
class CloudFileLoader:
    class Config(BaseModel):
        connection: str = ""
        path: str = ""
        format: Literal["auto", "csv", "tsv", "parquet", "json", "jsonl", "excel"] = "auto"
        limit: int = Field(0, ge=0)

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.connectors.storage import filesystem, full_path, read_frame
        from athena.connectors.store import resolve_connection

        cfg = self.Config(**ctx.config)
        if not cfg.connection:
            raise ValueError("Choose a storage connection (create one under Connections)")
        if not cfg.path.strip():
            raise ValueError("Enter the path of a file or folder")
        _, conn = resolve_connection(cfg.connection)
        fs = filesystem(conn)  # type: ignore[arg-type]
        target = full_path(conn, cfg.path)  # type: ignore[arg-type]
        paths = sorted(fs.glob(target)) if any(c in target for c in "*?[") else [target]
        if not paths:
            raise ValueError(f"No files match {cfg.path!r}")
        ctx.logger.info("Reading", connection=cfg.connection, files=len(paths), first=paths[0])
        frames = [read_frame(fs, p, cfg.format, cfg.limit or None) for p in paths]
        df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        if cfg.limit:
            df = df.head(cfg.limit)
        ctx.logger.info("Loaded", rows=len(df), cols=len(df.columns))
        return HandlerResult(outputs=[df], preview=preview_dataframe(df),
                             metrics={"rows": float(len(df)), "files": float(len(paths))})
