"""SaaS app connectors (``saas_<app>``), generated from the presets in saas_presets.py.

Each connector asks only for that app's credentials, tests them against the app's "who am I" endpoint, and lists
the ready-made resources. ``rest_source_config`` turns a connection + resource + parameters into the dlt REST
source config that the SaaS Fetch node runs (and exports).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, SecretStr, create_model

from athena.connectors.http_api import (
    HttpApiConfig,
    HttpApiConnector,
    fetch_frame,
    parse_json_object,
    rest_config,
)
from athena.connectors.saas_presets import PRESETS, Preset
from athena.sdk.connector import ConnectorBase, Resource, TestResult, connector
from athena.sdk.node import ui

if TYPE_CHECKING:
    import pandas as pd

SAAS_TYPES = ",".join(f"saas_{app}" for app in PRESETS)
"""Connector types the SaaS Fetch node accepts (the connection widget takes a comma-separated list)."""

PAGINATOR_MARKER = "__ATHENA_HAS_MORE_PAGINATOR__"


def config_model(p: Preset) -> type[BaseModel]:
    fields: dict[str, Any] = {c.name: ((SecretStr, SecretStr("")) if c.secret else (str, "")) for c in p.credentials}
    fields["base_url"] = (str, "")
    return create_model(f"{p.app.capitalize()}Config", **fields)  # type: ignore[call-overload,no-any-return]


def http_config(p: Preset, cfg: BaseModel, test_path: str = "") -> HttpApiConfig:
    """The preset's base URL and authentication as a generic REST connection."""
    values = {c.name: getattr(cfg, c.name) for c in p.credentials}
    plain = {k: v for k, v in values.items() if isinstance(v, str)}
    base = str(getattr(cfg, "base_url", "")).strip()
    if not base:
        missing = [c.label for c in p.credentials if "{" + c.name + "}" in p.base_url and not plain.get(c.name, "").strip()]
        if missing:
            raise ValueError(f"Set {', '.join(missing)} in the {p.label} connection")
        base = p.base_url.format(**{k: v.strip() for k, v in plain.items()})
    secret: SecretStr = values[p.token_field]
    if not secret.get_secret_value():
        label = next(c.label for c in p.credentials if c.name == p.token_field)
        raise ValueError(f"Set {label} in the {p.label} connection")
    common: dict[str, Any] = {"base_url": base, "headers": _json(p.headers), "test_path": test_path or p.test_path}
    if p.auth == "bearer":
        return HttpApiConfig(auth="bearer", token=secret, **common)
    if p.auth == "header":
        return HttpApiConfig(auth="api_key", token=secret, api_key_name=p.header_name, api_key_location="header", **common)
    username = plain["email"].strip() + ("/token" if p.auth == "basic_email_token" else "")  # Zendesk: email/token
    return HttpApiConfig(auth="basic", username=username, password=secret, **common)


def _json(headers: dict[str, str]) -> str:
    import json
    return json.dumps(headers) if headers else ""


def endpoint(p: Preset, resource: str, params_text: str) -> tuple[str, dict[str, Any], str, dict[str, Any]]:
    """(path, query parameters, records path, paginator spec): path placeholders are filled from the parameters."""
    r = p.resource(resource)
    given = parse_json_object(params_text, "Parameters")
    holes = re.findall(r"\{(\w+)\}", r.path)
    missing = [h for h in holes if not str(given.get(h, "")).strip()]
    if missing:
        example = ", ".join(f'"{h}": "..."' for h in holes)
        raise ValueError(f"{p.label} {r.name} needs {' and '.join(missing)} in Parameters, e.g. {{{example}}}")
    path = r.path.format(**{h: str(given[h]).strip() for h in holes})
    query = {**r.params, **{k: v for k, v in given.items() if k not in holes}}
    return path, query, r.data_selector, dict(r.paginator or p.paginator)


def rest_source_config(p: Preset, cfg: BaseModel, resource: str, params_text: str, live_paginator: bool = True) -> dict[str, Any]:
    """dlt rest_api_source config. ``live_paginator=False`` leaves a marker for the export to replace with code."""
    path, query, selector, spec = endpoint(p, resource, params_text)
    paginator: Any = spec
    if spec.get("type") == "has_more":
        kwargs = {k: v for k, v in spec.items() if k != "type"}
        if live_paginator:
            from athena.connectors.saas_paginator import _AthenaHasMorePaginator
            paginator = _AthenaHasMorePaginator(**kwargs)
        else:
            import json  # double quotes inside keep repr()'s outer quotes single, so the export can find it
            paginator = PAGINATOR_MARKER + json.dumps(kwargs)
    return rest_config(http_config(p, cfg), path, query, selector, paginator)


class SaasConnector(ConnectorBase):
    preset: Preset

    def test(self, cfg: BaseModel) -> TestResult:
        try:
            http = http_config(self.preset, cfg)
        except ValueError as exc:
            return TestResult(False, str(exc))
        return HttpApiConnector().test(http)

    def list(self, cfg: BaseModel, path: str | None = None) -> list[Resource]:
        return [Resource(path=r.name, name=r.name, kind="endpoint") for r in self.preset.resources]

    def read(self, cfg: BaseModel, query: str, limit: int | None = None) -> pd.DataFrame:
        """``query`` is a resource name; reads up to 3 pages."""
        df, _ = fetch_frame(rest_source_config(self.preset, cfg, query, ""), max_pages=3, name="athena_saas")
        return df.head(limit) if limit else df


def _register(p: Preset) -> None:
    fields = {c.name: ui(c.label, help=c.help) for c in p.credentials}
    fields["base_url"] = ui("Base URL override", help=f"Leave empty to use {p.base_url}. Set it for a proxy or a self-hosted edition.")
    cls = type(f"{p.app.capitalize()}Connector", (SaasConnector,), {"Config": config_model(p), "preset": p})
    connector(f"saas_{p.app}", label=p.label, category="api", description=f"{p.description} API docs: {p.docs}",
              library="dlt (REST API source)", license="Apache-2.0 (dlt)", fields=fields,
              extras={"dlt": "pip install 'athena-backend[api]'"})(cls)


for _preset in PRESETS.values():
    _register(_preset)
