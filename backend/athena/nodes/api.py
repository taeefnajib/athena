"""API Fetch: pull JSON records from a REST endpoint into a DataFrame (dlt; optional extra athena-backend[api])."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from athena.connectors.saas import SAAS_TYPES
from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe


@node(
    "api_fetch", reusable=False, label="API Fetch", category="data",
    description="Fetch JSON records from a REST API endpoint through a saved connection (pagination and nested JSON handled by dlt)",
    outputs=[Port("dataset", "dataset")],
    fields={
        "connection": ui("Connection", widget="connection", connector="http_api"),
        "path": ui("Endpoint path", help="Relative to the connection's base URL, e.g. /repos/dlt-hub/dlt/issues"),
        "params": ui("Query parameters", widget="textarea", mono=True, help='JSON, e.g. {"state": "open", "per_page": 100}'),
        "data_selector": ui("Records path", help="JSON path to the list of records, e.g. data.items. Empty = detect"),
        "paginator": ui("Pagination", help="auto: let dlt detect it (check the logs). none: a single request"),
        "page_param": ui("Page / offset / cursor parameter", help="Query parameter the paginator sets. Empty = page, offset or cursor"),
        "page_size": ui("Page size", min=1, help="Offset pagination only: rows per request (sent as limit)"),
        "response_path": ui("Response path", help="page_number/offset: path to the total; cursor: path to the next cursor; next_url: path to the next page URL"),
        "max_pages": ui("Max pages", min=0, help="Safety limit on requests. 0 = all pages"),
        "nested": ui("Nested data", help="flatten: objects become a__b columns (lists are left out). json: keep nested values as JSON text"),
    },
    code=EXPORT["api_fetch"],
)
class ApiFetchHandler:
    class Config(BaseModel):
        connection: str = ""
        path: str = ""
        params: str = ""
        data_selector: str = ""
        paginator: Literal["auto", "none", "page_number", "offset", "cursor", "next_url", "link_header"] = "auto"
        page_param: str = ""
        page_size: int = Field(100, ge=1)
        response_path: str = ""
        max_pages: int = Field(10, ge=0)
        nested: Literal["flatten", "json"] = "flatten"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.connectors.http_api import (
            fetch_frame,
            paginator_config,
            parse_json_object,
            rest_config,
        )
        from athena.connectors.store import resolve_connection

        cfg = self.Config(**ctx.config)
        if not cfg.connection:
            raise ValueError("Choose a REST API connection (create one under Connections)")
        _, conn = resolve_connection(cfg.connection)
        config = rest_config(conn, cfg.path, parse_json_object(cfg.params, "Query parameters"), cfg.data_selector,  # type: ignore[arg-type]
                             paginator_config(cfg.paginator, cfg.page_param, cfg.page_size, cfg.response_path))
        ctx.logger.info("Fetching", url=conn.base_url.rstrip("/") + "/" + cfg.path.lstrip("/"),  # type: ignore[attr-defined]
                        pagination=cfg.paginator, max_pages=cfg.max_pages or "all")
        try:
            df, children = fetch_frame(config, cfg.max_pages, cfg.nested, name="athena_api")
        except Exception as exc:
            cause = exc.__cause__ or exc
            raise ValueError(f"API fetch failed: {type(cause).__name__}: {str(cause).splitlines()[0][:300]}") from exc
        if children:
            ctx.logger.warning(f"Nested lists were left out (dlt child tables: {', '.join(children)}). Set Nested data to json to keep them.")
        ctx.logger.info("Fetched", rows=len(df), cols=len(df.columns))
        return HandlerResult(outputs=[df], preview=preview_dataframe(df), metrics={"rows": float(len(df))})


@node(
    "saas_fetch", reusable=False, label="SaaS Fetch", category="data",
    description="Pull records from GitHub, Stripe, HubSpot, Jira, Zendesk or Shopify through a saved connection (ready-made endpoints and paging)",
    outputs=[Port("dataset", "dataset")],
    fields={
        "connection": ui("Connection", widget="connection", connector=SAAS_TYPES),
        "resource": ui("Resource", widget="resource", connection_field="connection",
                       help="What to read. The list follows the connection's app (GitHub issues, Stripe invoices, HubSpot deals...)."),
        "params": ui("Parameters", widget="textarea", mono=True,
                     help='JSON. Fills path parts and adds query parameters, e.g. {"owner": "dlt-hub", "repo": "dlt"} or {"jql": "project = ABC"}'),
        "max_pages": ui("Max pages", min=0, help="Safety limit on requests. 0 = all pages"),
        "nested": ui("Nested data", help="flatten: objects become a__b columns (lists are left out). json: keep nested values as JSON text"),
    },
    code=EXPORT["saas_fetch"],
)
class SaasFetchHandler:
    class Config(BaseModel):
        connection: str = ""
        resource: str = ""
        params: str = ""
        max_pages: int = Field(10, ge=0)
        nested: Literal["flatten", "json"] = "flatten"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.connectors.http_api import fetch_frame
        from athena.connectors.saas import SaasConnector, rest_source_config
        from athena.connectors.store import resolve_connection

        cfg = self.Config(**ctx.config)
        if not cfg.connection:
            raise ValueError("Choose a SaaS connection (create one under Connections: GitHub, Stripe, HubSpot, Jira, Zendesk or Shopify)")
        impl, conn = resolve_connection(cfg.connection)
        if not isinstance(impl, SaasConnector):
            raise TypeError(f"{cfg.connection!r} isn't a SaaS app connection: use API Fetch for a generic REST API")
        preset = impl.preset
        if not cfg.resource.strip():
            raise ValueError(f"Choose a {preset.label} resource: {', '.join(r.name for r in preset.resources)}")
        config = rest_source_config(preset, conn, cfg.resource, cfg.params)
        ctx.logger.info("Fetching", app=preset.label, resource=cfg.resource, url=config["client"]["base_url"] + config["resources"][0]["endpoint"]["path"],
                        max_pages=cfg.max_pages or "all")
        try:
            df, children = fetch_frame(config, cfg.max_pages, cfg.nested, name="athena_saas")
        except Exception as exc:
            cause = exc.__cause__ or exc
            hint = " (check the credentials and their scopes)" if any(c in str(cause) for c in ("401", "403")) else ""
            raise ValueError(f"{preset.label} fetch failed{hint}: {type(cause).__name__}: {str(cause).splitlines()[0][:300]}") from exc
        if children:
            ctx.logger.warning(f"Nested lists were left out (dlt child tables: {', '.join(children)}). Set Nested data to json to keep them.")
        ctx.logger.info("Fetched", rows=len(df), cols=len(df.columns))
        return HandlerResult(outputs=[df], preview=preview_dataframe(df), metrics={"rows": float(len(df))})
