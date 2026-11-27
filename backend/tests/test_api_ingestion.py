"""REST API connector and the API Fetch node (dlt), against a local mock API covering every pagination style."""
from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("dlt")

from fastapi.testclient import TestClient  # noqa: E402

import athena.core.executor as exe  # noqa: E402
from athena.connectors import secrets  # noqa: E402
from athena.core.codegen import pipeline_to_python  # noqa: E402
from athena.core.events import EventBroker  # noqa: E402
from athena.main import app  # noqa: E402
from athena.runtime.engine import run_spec  # noqa: E402
from athena.schemas.pipeline import PipelineSpec  # noqa: E402

client = TestClient(app)
ROWS = [{"id": i, "name": f"user{i}", "address": {"city": ["Dhaka", "Berlin"][i % 2], "zip": f"{1000 + i}"}, "tags": ["a", "b"][: i % 3]}
        for i in range(10)]
TOKEN = "s3cret-token"


class MockApi(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def _send(self, body: object, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        base = f"http://127.0.0.1:{self.server.server_port}"
        auth = self.headers.get("Authorization", "")
        if url.path == "/basic":
            ok = auth == "Basic " + base64.b64encode(b"ana:pw").decode()
            return self._send(ROWS[:3] if ok else {"error": "no"}, 200 if ok else 401)
        if url.path == "/keyed":
            return self._send({"items": ROWS[:2]} if q.get("key") == TOKEN else {"error": "no"}, 200 if q.get("key") == TOKEN else 401)
        if auth != f"Bearer {TOKEN}":
            return self._send({"error": "unauthorized"}, 401)
        if url.path == "/pages":  # page number + total pages, records under data.items
            page = int(q.get("page", 1))
            if q.get("status") not in (None, "open"):
                return self._send({"error": "bad param"}, 400)
            return self._send({"data": {"items": ROWS[(page - 1) * 3: page * 3]}, "total_pages": 4})
        if url.path == "/offset":
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 3))
            return self._send({"results": ROWS[off: off + lim], "total": len(ROWS)})
        if url.path == "/cursor":
            start = int(q.get("cursor") or 0)
            nxt = start + 4 if start + 4 < len(ROWS) else None
            return self._send({"records": ROWS[start: start + 4], "cursors": {"next": str(nxt) if nxt else None}})
        if url.path == "/next":
            page = int(q.get("page", 1))
            nxt = f"{base}/next?page={page + 1}" if page * 5 < len(ROWS) else None
            return self._send({"results": ROWS[(page - 1) * 5: page * 5], "next": nxt})
        if url.path == "/link":
            page = int(q.get("page", 1))
            hdr = {"Link": f'<{base}/link?page={page + 1}>; rel="next"'} if page * 4 < len(ROWS) else {}
            return self._send(ROWS[(page - 1) * 4: page * 4], headers=hdr)
        return self._send({"error": "not found"}, 404)


@pytest.fixture(scope="module")
def api_url():
    srv = HTTPServer(("127.0.0.1", 0), MockApi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def memory_secrets(monkeypatch, tmp_path):
    old = secrets.get_store()
    secrets.set_store(secrets.MemoryStore())
    monkeypatch.setenv("DLT_DATA_DIR", str(tmp_path / "dlt-home"))  # keep exported scripts out of ~/.dlt
    yield
    secrets.set_store(old)


def _connect(api_url: str, name: str = "mock", **config: object) -> None:
    body = {"base_url": api_url, "auth": "bearer", "token": TOKEN, **config}
    assert client.put("/api/connections", json={"name": name, "type": "http_api", "config": body}).status_code == 200


def _spec(**config: object) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "api", "nodes": [
        {"id": "a1", "type": "api_fetch", "position": {"x": 0, "y": 0}, "config": {"connection": "mock", **config}}], "edges": []})


def _run(spec: PipelineSpec, tmp: Path) -> tuple[list[dict], dict]:
    events: list[dict] = []
    arts: dict = {}
    status = run_spec(spec, "api", events.append, lambda: False, tmp / "cache", artifacts_out=arts)
    errors = [e["error"]["message"] for e in events if e["type"] == "node_finish" and e["status"] == "error"]
    assert status == "completed", errors
    return events, arts


def test_connection_test_reports_status_and_bad_credentials(api_url: str):
    ok = client.post("/api/connections/test", json={"type": "http_api", "config": {
        "base_url": api_url, "auth": "bearer", "token": TOKEN, "test_path": "/pages"}}).json()
    assert ok["ok"] and "HTTP 200" in ok["message"] and "application/json" in ok["message"]
    bad = client.post("/api/connections/test", json={"type": "http_api", "config": {
        "base_url": api_url, "auth": "bearer", "token": "wrong", "test_path": "/pages"}}).json()
    assert not bad["ok"] and "401" in bad["message"] and "credentials" in bad["message"]


@pytest.mark.parametrize(("path", "config", "rows"), [
    ("/pages", {"paginator": "page_number", "data_selector": "data.items", "response_path": "total_pages", "params": '{"status": "open"}'}, 10),
    ("/offset", {"paginator": "offset", "page_size": 3, "response_path": "total", "data_selector": "results"}, 10),
    ("/cursor", {"paginator": "cursor", "response_path": "cursors.next", "data_selector": "records"}, 10),
    ("/next", {"paginator": "next_url", "response_path": "next", "data_selector": "results"}, 10),
    ("/link", {"paginator": "link_header"}, 10),
    ("/pages", {"paginator": "page_number", "data_selector": "data.items", "max_pages": 2}, 6),  # page limit
])
def test_every_pagination_style(api_url: str, tmp_path: Path, path: str, config: dict, rows: int):
    _connect(api_url)
    events, arts = _run(_spec(path=path, **config), tmp_path)
    df = arts[("a1", 0)]
    assert len(df) == rows and sorted(df["id"]) == list(range(rows))
    assert "address__city" in df.columns  # nested objects flattened
    logs = [e["msg"] for e in events if e["type"] == "node_log"]
    assert any("Nested lists were left out" in m for m in logs)  # tags became a dlt child table


def test_nested_json_mode_keeps_lists(api_url: str, tmp_path: Path):
    _connect(api_url)
    _, arts = _run(_spec(path="/link", paginator="link_header", nested="json"), tmp_path)
    df = arts[("a1", 0)]
    assert "tags" in df.columns and "address" in df.columns


@pytest.mark.parametrize(("path", "config", "rows"), [
    ("/keyed", {"auth": "api_key", "api_key_name": "key", "api_key_location": "query"}, 2),
    ("/basic", {"auth": "basic", "username": "ana", "password": "pw"}, 3),
])
def test_api_key_and_basic_auth(api_url: str, tmp_path: Path, path: str, config: dict, rows: int):
    _connect(api_url, **config)
    _, arts = _run(_spec(path=path, paginator="none", data_selector="items" if path == "/keyed" else ""), tmp_path)
    assert len(arts[("a1", 0)]) == rows


def test_bad_credentials_are_a_clear_node_error(api_url: str, tmp_path: Path):
    _connect(api_url, token="wrong")
    events: list[dict] = []
    run_spec(_spec(path="/pages", paginator="none"), "api", events.append, lambda: False, tmp_path / "cache")
    err = next(e for e in events if e["type"] == "node_finish")
    assert err["status"] == "error" and "API fetch failed" in err["error"]["message"] and "401" in err["error"]["message"]


def test_export_matches_athena_and_hides_the_token(api_url: str, tmp_path: Path, monkeypatch):
    from tests.test_export_equivalence import run_both
    _connect(api_url)
    spec = _spec(path="/pages", paginator="page_number", data_selector="data.items", response_path="total_pages")
    code = pipeline_to_python(spec)
    assert TOKEN not in code and "os.environ['ATHENA_MOCK_TOKEN']" in code
    assert code.index('RUNTIME__DLTHUB_TELEMETRY') < code.index("import dlt")  # telemetry off before dlt loads
    monkeypatch.setenv("ATHENA_MOCK_TOKEN", TOKEN)
    run_both(spec, tmp_path)


@pytest.mark.asyncio
async def test_api_fetch_runs_in_the_worker(api_url: str, monkeypatch):
    # The worker is another process: give it the token through an env:// reference (the test's in-memory
    # secret store isn't shared across processes; the real OS keychain is).
    monkeypatch.setenv("MOCK_API_TOKEN", TOKEN)
    exe.pool.shutdown()  # a standby started before setenv wouldn't see the variable
    _connect(api_url, token="env://MOCK_API_TOKEN")
    broker = EventBroker()
    q = broker.subscribe("api-worker")
    await exe.execute(_spec(path="/next", paginator="next_url", data_selector="results"), "api-worker", broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    finish = next(e for e in events if e.type == "node_finish")
    assert finish.status == "success", finish.error
    assert finish.metrics["rows"] == 10


def test_dlt_working_files_are_cleaned_up(api_url: str, tmp_path: Path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    _connect(api_url)
    _run(_spec(path="/link", paginator="link_header"), tmp_path)
    assert list((tmp_path / "tmp").iterdir()) == []  # the short-lived dlt folder is gone
