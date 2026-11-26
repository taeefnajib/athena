"""SQL databases through SQLAlchemy: PostgreSQL, MySQL/MariaDB, SQLite, DuckDB, SQL Server, or any SQLAlchemy URL."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, SecretStr

from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui

if TYPE_CHECKING:
    import pandas as pd

# dialect -> (SQLAlchemy driver name, import name of the DB driver, pip extra)
DRIVERS: dict[str, tuple[str, str | None, str | None]] = {
    "postgresql": ("postgresql+psycopg", "psycopg", "postgres"),
    "mysql": ("mysql+pymysql", "pymysql", "mysql"),
    "sqlite": ("sqlite", None, None),
    "duckdb": ("duckdb", "duckdb_engine", "duckdb"),
    "mssql": ("mssql+pyodbc", "pyodbc", "mssql"),
}
DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306, "mssql": 1433}


class SqlConfig(BaseModel):
    dialect: Literal["postgresql", "mysql", "sqlite", "duckdb", "mssql", "url"] = "postgresql"
    host: str = "localhost"
    port: int = 5432
    database: str = ""
    username: str = ""
    password: SecretStr = SecretStr("")
    url: str = ""
    """Full SQLAlchemy URL for dialect="url" (without the password; that goes in Password)."""
    schema_: str = ""


def engine_url(cfg: SqlConfig) -> Any:
    from sqlalchemy.engine import URL, make_url

    if cfg.dialect == "url":
        if not cfg.url:
            raise ValueError("Enter a SQLAlchemy URL, e.g. postgresql+psycopg://user@host/db")
        url = make_url(cfg.url)
        pw = cfg.password.get_secret_value()
        return url.set(password=pw) if pw else url
    driver, module, extra = DRIVERS[cfg.dialect]
    if module is not None:
        import importlib.util
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"The {cfg.dialect} driver isn't installed. Run: pip install 'athena-backend[{extra}]'")
    if cfg.dialect in ("sqlite", "duckdb"):
        if not cfg.database:
            raise ValueError("Enter the database file path (or :memory:)")
        return URL.create(driver, database=cfg.database)
    return URL.create(driver, username=cfg.username or None, password=cfg.password.get_secret_value() or None,
                      host=cfg.host or None, port=cfg.port or None, database=cfg.database or None)


def make_engine(cfg: SqlConfig) -> Any:
    from sqlalchemy import create_engine
    return create_engine(engine_url(cfg), pool_pre_ping=True)


@connector(
    "sql", label="SQL Database", category="database",
    description="PostgreSQL, MySQL/MariaDB, SQLite, DuckDB, SQL Server, or any SQLAlchemy URL.",
    library="SQLAlchemy", license="MIT (SQLAlchemy; drivers have their own licenses)",
    fields={
        "dialect": ui("Database"),
        "host": ui("Host"),
        "port": ui("Port"),
        "database": ui("Database name or file", help="For SQLite and DuckDB: the file path, or :memory:"),
        "username": ui("Username"),
        "password": ui("Password", help="Stored in your OS keychain. Or enter env://VAR to read an environment variable."),
        "url": ui("SQLAlchemy URL", help="Only for Database = url. Leave the password out of the URL."),
        "schema_": ui("Default schema"),
    },
    extras={
        "PostgreSQL": "pip install 'athena-backend[postgres]'",
        "MySQL / MariaDB": "pip install 'athena-backend[mysql]'",
        "DuckDB": "pip install 'athena-backend[duckdb]'",
        "SQL Server": "pip install 'athena-backend[mssql]'",
    },
)
class SqlConnector(ConnectorBase):
    Config = SqlConfig

    def test(self, cfg: SqlConfig) -> TestResult:
        from sqlalchemy import inspect, text
        try:
            engine = make_engine(cfg)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                version = engine.dialect.server_version_info
                tables = len(inspect(conn).get_table_names(schema=cfg.schema_ or None))
        except Exception as exc:
            return TestResult(False, _clean_error(exc))
        ver = ".".join(map(str, version)) if version else ""
        return TestResult(True, f"Connected to {engine.dialect.name} {ver}".strip() + f" · {tables} tables",
                          {"dialect": engine.dialect.name, "tables": tables})

    def list(self, cfg: SqlConfig, path: str | None = None) -> list[Resource]:
        from sqlalchemy import inspect
        engine = make_engine(cfg)
        with engine.connect() as conn:
            insp = inspect(conn)
            if path is None and cfg.dialect not in ("sqlite", "duckdb") and not cfg.schema_:
                return [Resource(s, s, "schema", True) for s in insp.get_schema_names()]
            schema = path or cfg.schema_ or None
            prefix = f"{schema}." if schema else ""
            tables = [Resource(f"{prefix}{t}", t, "table") for t in insp.get_table_names(schema=schema)]
            views = [Resource(f"{prefix}{v}", v, "view") for v in insp.get_view_names(schema=schema)]
            return tables + views

    def read(self, cfg: SqlConfig, query: str, limit: int | None = None) -> pd.DataFrame:
        import pandas as pd
        from sqlalchemy import text
        engine = make_engine(cfg)
        with engine.connect() as conn:
            if limit:
                chunks = pd.read_sql_query(text(query), conn, chunksize=limit)
                return next(iter(chunks), pd.DataFrame())
            return pd.read_sql_query(text(query), conn)


def _clean_error(exc: Exception) -> str:
    msg = str(getattr(exc, "orig", None) or exc).strip().splitlines()[0]
    return f"{type(exc).__name__}: {msg}"[:400]
