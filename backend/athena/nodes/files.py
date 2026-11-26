"""Columnar files and SQL transforms: Parquet Loader and SQL Transform (DuckDB)."""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe


def _cols(text: str) -> list[str] | None:
    cols = [c.strip() for c in text.split(",") if c.strip()]
    return cols or None


def _code_parquet(v: dict[str, Any]) -> str:
    cols = f", columns={_cols(v['columns'])!r}" if _cols(v["columns"]) else ""
    head = f".head({int(v['limit'])})" if v["limit"] else ""
    return (f"# --- Node {v['id']}: Parquet Loader ---\nimport pandas as pd\n"
            f"df_{v['var']} = pd.read_parquet({v['path']!r}{cols}){head}\n")


@node(
    "parquet_loader", label="Parquet Loader", category="data",
    description="Load a Parquet file, or a folder of Parquet files (a partitioned dataset)",
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("File or folder", widget="file", accept=".parquet,.pq"),
        "columns": ui("Columns", help="Comma-separated; empty = all. Reading fewer columns is much faster."),
        "limit": ui("Row limit", min=0, help="0 = all rows"),
    },
    code=_code_parquet,
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


def _code_duckdb(v: dict[str, Any]) -> str:
    src = v["src"]
    second = v["src_test"]
    lines = [f"# --- Node {v['id']}: SQL Transform (DuckDB) ---", "import duckdb"]
    if src != "???":
        lines.append(f"in1 = df_{src}")
    if second != "???":
        lines.append(f"in2 = df_{second}")
    lines.append(f"df_{v['var']} = duckdb.sql({v['query']!r}).df()")
    return "\n".join(lines) + "\n"


@node(
    "duckdb_sql", label="SQL Transform", category="data",
    description="Transform data with SQL (DuckDB): filter, join, aggregate, window functions. Inputs are tables in1 and in2.",
    inputs=[Port("in1", "dataset"), Port("in2", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "query": ui("SQL", widget="textarea", mono=True,
                    help="Connected inputs are tables in1 and in2. You can also read files directly: "
                         "SELECT * FROM 'data/*.parquet' or read_csv('file.csv')."),
    },
    code=_code_duckdb,
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


def _code_cloud(v: dict[str, Any]) -> str:
    """Exported code reads the same URL with pandas; credentials come from the environment, never the file."""
    header = f"# --- Node {v['id']}: Cloud File Loader (connection {v['connection']!r}) ---\nimport pandas as pd\n"
    try:
        from athena.connectors.storage import StorageConfig, detect_format, url
        from athena.connectors.store import get_connection
        conn = get_connection(v["connection"])
        cfg = StorageConfig(**conn["config"])
    except Exception:
        return header + f"# Connection {v['connection']!r} isn't saved on this machine; set the URL yourself.\ndf_{v['var']} = pd.read_parquet('s3://bucket/{v['path']}')\n"
    target = url(cfg, v["path"])
    kind = detect_format(target, v["format"]) or "parquet"
    opts: dict[str, Any] = {}
    note = {"s3": "# Credentials: the standard AWS chain (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, ~/.aws, or an instance role).",
            "gcs": "# Credentials: GOOGLE_APPLICATION_CREDENTIALS or Application Default Credentials.",
            "azure": "# Credentials: set AZURE_STORAGE_KEY (or use Azure default credentials).",
            "local": ""}[cfg.protocol]
    if cfg.protocol == "s3" and cfg.endpoint_url:
        opts["client_kwargs"] = {"endpoint_url": cfg.endpoint_url}
    if cfg.protocol == "azure" and cfg.azure_account_name:
        opts["account_name"] = cfg.azure_account_name
    if cfg.anonymous:
        opts["anon" if cfg.protocol != "gcs" else "token"] = True if cfg.protocol != "gcs" else "anon"
    reader = {"parquet": "read_parquet", "csv": "read_csv", "tsv": "read_csv", "json": "read_json",
              "jsonl": "read_json", "excel": "read_excel"}[kind]
    extra = ", sep='\t'" if kind == "tsv" else ", lines=True" if kind == "jsonl" else ""
    so = ""
    if cfg.protocol == "azure":
        so = f", storage_options={{**{opts!r}, 'account_key': os.environ.get('AZURE_STORAGE_KEY')}}"
        header += "import os\n"
    elif opts:
        so = f", storage_options={opts!r}"
    head = f".head({int(v['limit'])})" if v["limit"] else ""
    return header + (note + "\n" if note else "") + f"df_{v['var']} = pd.{reader}({target!r}{extra}{so}){head}\n"


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
    code=_code_cloud,
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
