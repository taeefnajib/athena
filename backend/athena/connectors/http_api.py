"""REST/JSON APIs through dlt's declarative REST source (optional extra: athena-backend[api]).

dlt handles pagination (detected or configured), nested JSON (objects become ``a__b`` columns, lists become
child tables), retries and rate-limit back-off. Athena loads into a private DuckDB file per run and returns the
root table as a DataFrame.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, SecretStr

from athena.sdk.connector import ConnectorBase, TestResult, connector
from athena.sdk.node import ui

if TYPE_CHECKING:
    import pandas as pd

# Athena never phones home, and neither may its dependencies: dlt collects anonymous telemetry unless told not to.
os.environ.setdefault("RUNTIME__DLTHUB_TELEMETRY", "false")

INSTALL_HINT = "API ingestion needs dlt. Run: pip install 'athena-backend[api]' (in backend/: uv sync --extra api)"
PAGINATORS = ("auto", "none", "page_number", "offset", "cursor", "next_url", "link_header")


class HttpApiConfig(BaseModel):
    base_url: str = "https://api.example.com"
    auth: Literal["none", "bearer", "api_key", "basic"] = "none"
    token: SecretStr = SecretStr("")
    api_key_name: str = "X-API-Key"
    api_key_location: Literal["header", "query"] = "header"
    username: str = ""
    password: SecretStr = SecretStr("")
    headers: str = ""
    test_path: str = ""


def parse_json_object(text: str, what: str) -> dict[str, Any]:
    if not str(text).strip():
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{what} must be a JSON object, e.g. {{\"key\": \"value\"}}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object")
    return value


def auth_config(cfg: HttpApiConfig) -> dict[str, Any] | None:
    secret = cfg.token.get_secret_value()
    if cfg.auth == "bearer":
        return {"type": "bearer", "token": secret}
    if cfg.auth == "api_key":
        return {"type": "api_key", "name": cfg.api_key_name, "api_key": secret, "location": cfg.api_key_location}
    if cfg.auth == "basic":
        return {"type": "http_basic", "username": cfg.username, "password": cfg.password.get_secret_value()}
    return None


def paginator_config(kind: str, page_param: str, page_size: int, response_path: str) -> dict[str, Any] | None:
    """Athena's simple paginator choice -> a dlt paginator config (None = let dlt detect it)."""
    path = response_path.strip() or None
    if kind == "auto":
        return None
    if kind == "none":
        return {"type": "single_page"}
    if kind == "page_number":
        return {"type": "page_number", "base_page": 1, "page_param": page_param or "page", "total_path": path, "stop_after_empty_page": True}
    if kind == "offset":
        return {"type": "offset", "limit": page_size, "offset_param": page_param or "offset", "limit_param": "limit",
                "total_path": path, "stop_after_empty_page": True}
    if kind == "cursor":
        return {"type": "cursor", "cursor_path": path or "cursors.next", "cursor_param": page_param or "cursor"}
    if kind == "next_url":
        return {"type": "json_link", "next_url_path": path or "next"}
    if kind == "link_header":
        return {"type": "header_link"}
    raise ValueError(f"Unknown paginator {kind!r}")


def rest_config(cfg: HttpApiConfig, path: str, params: dict[str, Any], data_selector: str, paginator: dict[str, Any] | None) -> dict[str, Any]:
    client: dict[str, Any] = {"base_url": cfg.base_url.rstrip("/") + "/"}
    if (auth := auth_config(cfg)) is not None:
        client["auth"] = auth
    if headers := parse_json_object(cfg.headers, "Headers"):
        client["headers"] = headers
    endpoint: dict[str, Any] = {"path": path.lstrip("/")}
    if params:
        endpoint["params"] = params
    if data_selector.strip():
        endpoint["data_selector"] = data_selector.strip()
    if paginator is not None:
        endpoint["paginator"] = paginator
    return {"client": client, "resources": [{"name": "data", "endpoint": endpoint, "write_disposition": "replace"}]}


def fetch_frame(config: dict[str, Any], max_pages: int = 0, nested: str = "flatten",
                name: str = "athena_api") -> tuple[pd.DataFrame, list[str]]:
    """Run a dlt REST source into a private DuckDB file; returns (root table, names of child tables).

    dlt's working files nest deeply, so they go in a short temporary folder (Windows limits paths to 260
    characters) that is removed afterwards; the result is already in memory by then."""
    if importlib.util.find_spec("dlt") is None:
        raise RuntimeError(INSTALL_HINT)
    import shutil
    import tempfile

    work_dir = Path(tempfile.mkdtemp(prefix="athena_dlt_"))
    try:
        return _fetch(config, work_dir, max_pages, nested, name)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _fetch(config: dict[str, Any], work_dir: Path, max_pages: int, nested: str, name: str) -> tuple[pd.DataFrame, list[str]]:
    import dlt
    import pandas as pd
    from dlt.sources.rest_api import rest_api_source

    source = rest_api_source(config)
    if nested == "json":
        source.max_table_nesting = 0  # keep nested objects and lists as JSON in one column
    if max_pages:
        source.resources["data"].add_limit(max_pages)
    pipeline = dlt.pipeline(pipeline_name=name, destination=dlt.destinations.duckdb(str(work_dir / "store.duckdb")),
                            dataset_name="fetched", pipelines_dir=str(work_dir / "pipelines"))
    pipeline.run(source)
    tables = pipeline.default_schema.data_table_names()
    if "data" not in tables:
        return pd.DataFrame(), []
    import duckdb  # read the table directly (dlt's dataset reader depends on sqlglot versions)
    with duckdb.connect(str(work_dir / "store.duckdb"), read_only=True) as con:
        df = con.execute("SELECT * FROM fetched.data").df()
    return df.drop(columns=[c for c in ("_dlt_load_id", "_dlt_id") if c in df.columns]), [t for t in tables if t.startswith("data__")]


@connector(
    "http_api", label="REST API", category="api",
    description="Any JSON REST API: base URL, authentication and headers. Pagination and nested JSON are handled by dlt.",
    library="dlt (REST API source)", license="Apache-2.0 (dlt)",
    fields={
        "base_url": ui("Base URL", help="e.g. https://api.github.com"),
        "auth": ui("Authentication"),
        "token": ui("Token / API key", help="Bearer token or API key value. Stored in your OS keychain, or env://VAR"),
        "api_key_name": ui("API key name", help="Header or query parameter that carries the API key"),
        "api_key_location": ui("API key in"),
        "username": ui("Username", help="Basic authentication"),
        "password": ui("Password", help="Basic authentication. Stored in your OS keychain, or env://VAR"),
        "headers": ui("Extra headers", widget="textarea", mono=True, help='Non-secret headers as JSON, e.g. {"Accept": "application/json"}'),
        "test_path": ui("Test path", help="Path requested by Test connection, e.g. /users?per_page=1"),
    },
    extras={"dlt": "pip install 'athena-backend[api]'"},
)
class HttpApiConnector(ConnectorBase):
    Config = HttpApiConfig

    def test(self, cfg: HttpApiConfig) -> TestResult:
        import requests  # comes with dlt; also a dependency of many base packages

        url = cfg.base_url.rstrip("/") + "/" + cfg.test_path.lstrip("/")
        headers = parse_json_object(cfg.headers, "Headers")
        params: dict[str, str] = {}
        auth = None
        secret = cfg.token.get_secret_value()
        if cfg.auth == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        elif cfg.auth == "api_key":
            (headers if cfg.api_key_location == "header" else params)[cfg.api_key_name] = secret
        elif cfg.auth == "basic":
            auth = (cfg.username, cfg.password.get_secret_value())
        try:
            r = requests.get(url, headers=headers, params=params, auth=auth, timeout=15)
        except Exception as exc:
            return TestResult(False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        kind = r.headers.get("Content-Type", "").split(";")[0]
        if r.status_code >= 400:
            return TestResult(False, f"HTTP {r.status_code} from {url}" + (" (check the credentials)" if r.status_code in (401, 403) else ""))
        return TestResult(True, f"HTTP {r.status_code} · {kind or 'unknown content type'} · {len(r.content):,} bytes", {"status": r.status_code})

    def read(self, cfg: HttpApiConfig, query: str, limit: int | None = None) -> pd.DataFrame:
        """``query`` is an endpoint path; reads up to 5 pages with auto-detected pagination."""
        df, _ = fetch_frame(rest_config(cfg, query, {}, "", None), max_pages=5)
        return df.head(limit) if limit else df
