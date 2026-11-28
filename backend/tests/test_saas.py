"""SaaS app connectors and the SaaS Fetch node, against mock servers that mimic each API's auth and paging.

The mocks are strict where the real APIs are: GitHub wants its Accept/version headers, Jira's issue search
needs a JQL query, Shopify rejects other parameters next to page_info, and Zendesk keeps a cursor on its last
page (paging must stop on has_more). Real services are never called.
"""
from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("dlt")

from fastapi.testclient import TestClient

from athena.connectors import secrets
from athena.core.codegen import pipeline_to_python
from athena.main import app
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec

client = TestClient(app)
TOKEN = "tok-123"
N = 11  # records per collection: never a multiple of the page size


def _rows(prefix: str, n: int = N) -> list[dict]:
    return [{"id": f"{prefix}_{i}", "n": i, "meta": {"kind": ["a", "b"][i % 2]}} for i in range(n)]


class MockSaas(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def _send(self, body: object, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self) -> None:
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        base = f"http://127.0.0.1:{self.server.server_port}"
        auth = self.headers.get("Authorization", "")
        bearer = auth == f"Bearer {TOKEN}"
        p = url.path

        if p.startswith("/github/"):
            if not bearer:
                return self._send({"message": "Bad credentials"}, 401)
            if self.headers.get("Accept") != "application/vnd.github+json" or not self.headers.get("X-GitHub-Api-Version"):
                return self._send({"message": "missing headers"}, 400)
            if p == "/github/user":
                return self._send({"login": "me"})
            if p in ("/github/user/repos", "/github/repos/acme/app/issues"):
                if p.endswith("issues") and q.get("state") != "all":
                    return self._send({"message": "expected state=all"}, 400)
                page, size = int(q.get("page", 1)), 4
                rows = _rows("gh")[(page - 1) * size: page * size]
                extra = "&state=all" if p.endswith("issues") else ""
                link = {"Link": f'<{base}{p}?page={page + 1}&per_page=100{extra}>; rel="next"'} if page * size < N else {}
                return self._send(rows, headers=link)

        if p.startswith("/stripe/v1/"):
            if not bearer:
                return self._send({"error": {"message": "Invalid API Key"}}, 401)
            if p == "/stripe/v1/balance":
                return self._send({"object": "balance"})
            rows = _rows("cus")
            start = next((i + 1 for i, r in enumerate(rows) if r["id"] == q.get("starting_after")), 0)
            page = rows[start: start + 4]
            return self._send({"object": "list", "data": page, "has_more": start + 4 < N})

        if p.startswith("/hubspot/crm/v3/objects/"):
            if not bearer:
                return self._send({"message": "unauthorized"}, 401)
            start = int(q.get("after", 0))
            body: dict = {"results": _rows("hs")[start: start + 5]}
            if start + 5 < N:
                body["paging"] = {"next": {"after": str(start + 5)}}
            return self._send(body)

        if p.startswith("/jira/"):
            if auth != "Basic " + base64.b64encode(f"ana@acme.io:{TOKEN}".encode()).decode():
                return self._send({"errorMessages": ["unauthorized"]}, 401)
            if p == "/jira/myself":
                return self._send({"accountId": "1"})
            if p == "/jira/search/jql":
                if not q.get("jql") or q.get("fields") != "*navigable":
                    return self._send({"errorMessages": ["jql and fields are required"]}, 400)
                start = int(q.get("nextPageToken") or 0)
                body = {"issues": _rows("JIRA")[start: start + 4], "isLast": start + 4 >= N}
                if start + 4 < N:
                    body["nextPageToken"] = str(start + 4)
                return self._send(body)
            if p == "/jira/project/search":
                total, start, size = 120, int(q.get("startAt", 0)), int(q.get("maxResults", 50))
                return self._send({"values": _rows("P", total)[start: start + size], "total": total, "startAt": start})

        if p.startswith("/zendesk/"):
            if auth != "Basic " + base64.b64encode(f"ana@acme.io/token:{TOKEN}".encode()).decode():
                return self._send({"error": "Couldn't authenticate you"}, 401)
            if p == "/zendesk/users/me":
                return self._send({"user": {"id": 1}})
            if p == "/zendesk/tickets":
                start = int(q.get("page[after]") or 0)
                more = start + 5 < N
                # like the real API, the last page still carries a cursor: only has_more says stop
                return self._send({"tickets": _rows("t")[start: start + 5], "meta": {"has_more": more, "after_cursor": str(start + 5)},
                                   "links": {"next": f"{base}/zendesk/tickets?page[after]={start + 5}"}})

        if p.startswith("/shopify/"):
            if self.headers.get("X-Shopify-Access-Token") != TOKEN:
                return self._send({"errors": "[API] Invalid API key or access token"}, 401)
            if p == "/shopify/shop.json":
                return self._send({"shop": {"name": "acme"}})
            if p == "/shopify/orders.json":
                if "page_info" in q and "status" in q:
                    return self._send({"errors": "page_info can't be combined with other parameters"}, 400)
                if "page_info" not in q and q.get("status") != "any":
                    return self._send({"errors": "expected status=any"}, 400)
                start = int(q.get("page_info", 0))
                hdr = {"Link": f'<{base}/shopify/orders.json?limit=250&page_info={start + 4}>; rel="next"'} if start + 4 < N else {}
                return self._send({"orders": _rows("o")[start: start + 4]}, headers=hdr)
        return self._send({"error": "not found"}, 404)


@pytest.fixture(scope="module")
def api():
    srv = HTTPServer(("127.0.0.1", 0), MockSaas)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def memory_secrets(monkeypatch, tmp_path):
    old = secrets.get_store()
    secrets.set_store(secrets.MemoryStore())
    monkeypatch.setenv("DLT_DATA_DIR", str(tmp_path / "dlt-home"))
    yield
    secrets.set_store(old)


CREDS = {
    "github": ("github", {"token": TOKEN}),
    "stripe": ("stripe/v1", {"api_key": TOKEN}),
    "hubspot": ("hubspot", {"token": TOKEN}),
    "jira": ("jira", {"site": "acme", "email": "ana@acme.io", "api_token": TOKEN}),
    "zendesk": ("zendesk", {"subdomain": "acme", "email": "ana@acme.io", "api_token": TOKEN}),
    "shopify": ("shopify", {"shop": "acme", "access_token": TOKEN}),
}


def _connect(api: str, app_name: str, name: str | None = None, **override: object) -> str:
    prefix, creds = CREDS[app_name]
    body = {**creds, "base_url": f"{api}/{prefix}", **override}
    res = client.put("/api/connections", json={"name": name or app_name, "type": f"saas_{app_name}", "config": body})
    assert res.status_code == 200, res.text
    return name or app_name


def _spec(connection: str, resource: str, **config: object) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "saas", "nodes": [
        {"id": "s1", "type": "saas_fetch", "position": {"x": 0, "y": 0},
         "config": {"connection": connection, "resource": resource, "max_pages": 0, **config}}], "edges": []})


def _fetch(spec: PipelineSpec, tmp: Path):
    events: list[dict] = []
    arts: dict = {}
    run_spec(spec, "saas", events.append, lambda: False, tmp / "cache", artifacts_out=arts)
    finish = next(e for e in events if e["type"] == "node_finish")
    return finish, arts.get(("s1", 0))


@pytest.mark.parametrize(("app_name", "resource", "params", "rows", "prefix"), [
    ("github", "repos", "", N, "gh"),
    ("github", "issues", '{"owner": "acme", "repo": "app"}', N, "gh"),
    ("stripe", "customers", "", N, "cus"),
    ("hubspot", "contacts", "", N, "hs"),
    ("jira", "issues", '{"jql": "project = ABC"}', N, "JIRA"),
    ("jira", "projects", "", 120, "P"),
    ("zendesk", "tickets", "", N, "t"),
    ("shopify", "orders", "", N, "o"),
])
def test_every_app_pages_through_everything(api: str, tmp_path: Path, app_name, resource, params, rows, prefix):
    _connect(api, app_name)
    finish, df = _fetch(_spec(app_name, resource, params=params), tmp_path)
    assert finish["status"] == "success", finish.get("error")
    assert len(df) == rows and sorted(df["n"]) == list(range(rows)) and df["id"].iloc[0].startswith(prefix)
    assert "meta__kind" in df.columns


def test_connection_tests_use_each_apps_auth(api: str):
    for app_name, (prefix, creds) in CREDS.items():
        ok = client.post("/api/connections/test", json={"type": f"saas_{app_name}", "config": {**creds, "base_url": f"{api}/{prefix}"}}).json()
        assert ok["ok"], (app_name, ok)
        secret = next(k for k in creds if k in ("token", "api_key", "api_token", "access_token"))
        bad = client.post("/api/connections/test", json={"type": f"saas_{app_name}",
                                                          "config": {**creds, secret: "wrong", "base_url": f"{api}/{prefix}"}}).json()
        assert not bad["ok"] and "401" in bad["message"], (app_name, bad)
    missing = client.post("/api/connections/test", json={"type": "saas_jira", "config": {"email": "a@b.c", "api_token": "x"}}).json()
    assert not missing["ok"] and "Set Site" in missing["message"]


def test_clear_errors(api: str, tmp_path: Path):
    _connect(api, "github")
    finish, _ = _fetch(_spec("github", "issues", params='{"owner": "acme"}'), tmp_path)
    assert finish["status"] == "error" and "needs repo in Parameters" in finish["error"]["message"]
    finish, _ = _fetch(_spec("github", "wiki"), tmp_path)
    assert "no resource 'wiki'" in finish["error"]["message"] and "repos, issues" in finish["error"]["message"]
    _connect(api, "github", name="badgh", token="nope")
    finish, _ = _fetch(_spec("badgh", "repos"), tmp_path)
    assert "GitHub fetch failed (check the credentials" in finish["error"]["message"]


def test_default_base_urls_come_from_the_credentials():
    from athena.connectors.saas import http_config
    from athena.connectors.saas_presets import PRESETS
    from athena.connectors.store import build_config
    jira = http_config(PRESETS["jira"], build_config("saas_jira", {"site": "acme", "email": "a@b.c", "api_token": "t"}))
    assert jira.base_url == "https://acme.atlassian.net/rest/api/3" and jira.auth == "basic" and jira.username == "a@b.c"
    zd = http_config(PRESETS["zendesk"], build_config("saas_zendesk", {"subdomain": "acme", "email": "a@b.c", "api_token": "t"}))
    assert zd.base_url == "https://acme.zendesk.com/api/v2" and zd.username == "a@b.c/token"
    shop = http_config(PRESETS["shopify"], build_config("saas_shopify", {"shop": "acme", "access_token": "t"}))
    assert shop.base_url.startswith("https://acme.myshopify.com/admin/api/") and shop.api_key_name == "X-Shopify-Access-Token"


def test_resources_listed_and_node_spec_offers_them(api: str):
    _connect(api, "stripe")
    names = [r["name"] for r in client.get("/api/connections/stripe/resources").json()["resources"]]
    assert names == ["customers", "charges", "invoices", "subscriptions", "payment_intents", "products"]
    spec = next(n for n in client.get("/api/nodes").json()["nodes"] if n["type"] == "saas_fetch")
    fields = {f["id"]: f for f in spec["config"]}
    assert fields["connection"]["connector"].split(",") == [f"saas_{a}" for a in CREDS]
    assert fields["resource"]["type"] == "resource" and fields["resource"]["connection_field"] == "connection"


@pytest.mark.parametrize(("app_name", "resource", "env"), [("stripe", "customers", "ATHENA_STRIPE_API_KEY"),
                                                           ("zendesk", "tickets", "ATHENA_ZENDESK_API_TOKEN")])
def test_export_matches_athena_and_hides_secrets(api: str, tmp_path: Path, monkeypatch, app_name, resource, env):
    from tests.test_export_equivalence import run_both
    _connect(api, app_name)
    spec = _spec(app_name, resource)
    code = pipeline_to_python(spec)
    assert TOKEN not in code and f"os.environ[{env!r}]" in code
    assert "class _AthenaHasMorePaginator" in code and code.index("RUNTIME__DLTHUB_TELEMETRY") < code.index("import dlt")
    monkeypatch.setenv(env, TOKEN)
    run_both(spec, tmp_path)
