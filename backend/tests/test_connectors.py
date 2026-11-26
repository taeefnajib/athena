"""Connector SDK, saved connections, secret handling, the SQL connector and the SQL Query node."""
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import athena.core.executor as exe
from athena.config import settings
from athena.connectors import secrets
from athena.core.codegen import pipeline_to_python
from athena.core.events import EventBroker
from athena.main import app
from athena.schemas.pipeline import PipelineSpec

client = TestClient(app)


@pytest.fixture(autouse=True)
def memory_secrets():
    store = secrets.MemoryStore()
    old = secrets.get_store()
    secrets.set_store(store)
    yield store
    secrets.set_store(old)


@pytest.fixture
def sqlite_db(tmp_path: Path) -> str:
    path = tmp_path / "shop.db"
    with sqlite3.connect(path) as conn:
        pd.DataFrame({"id": [1, 2, 3], "spend": [10.5, 20.0, 7.25]}).to_sql("customers", conn, index=False)
    return str(path)


def _save(name: str, config: dict, conn_type: str = "sql"):
    return client.put("/api/connections", json={"name": name, "type": conn_type, "config": config})


def test_sql_connector_spec_marks_password_secret():
    specs = {c["type"]: c for c in client.get("/api/connectors").json()["connectors"]}
    sql = specs["sql"]
    assert sql["secret_fields"] == ["password"]
    pw = next(f for f in sql["config"] if f["id"] == "password")
    assert pw["type"] == "password" and pw["default"] == ""
    assert "SQLAlchemy" in sql["library"] and sql["license"]


def test_secrets_go_to_the_store_not_the_file(memory_secrets):
    r = _save("warehouse", {"dialect": "postgresql", "host": "db.internal", "username": "ana", "password": "s3cret"})
    assert r.status_code == 200, r.text
    on_disk = (settings.data_dir / "connections.json").read_text()
    assert "s3cret" not in on_disk
    assert memory_secrets.data == {"connection/warehouse/password": "s3cret"}
    listed = client.get("/api/connections").json()["connections"][0]
    assert listed["secrets"] == {"password": {"set": True, "ref": None}}
    assert "s3cret" not in json.dumps(listed)


def test_empty_secret_on_update_keeps_saved_one(memory_secrets):
    _save("wh", {"dialect": "postgresql", "password": "first"})
    _save("wh", {"dialect": "postgresql", "host": "new-host", "password": ""})
    assert memory_secrets.data["connection/wh/password"] == "first"
    assert client.get("/api/connections/wh").json()["config"]["host"] == "new-host"


def test_env_reference_is_resolved_at_use_time(monkeypatch):
    from athena.connectors.store import resolve_connection
    _save("ci", {"dialect": "postgresql", "password": "env://CI_DB_PASSWORD"})
    assert client.get("/api/connections/ci").json()["secrets"]["password"]["ref"] == "env://CI_DB_PASSWORD"
    monkeypatch.setenv("CI_DB_PASSWORD", "from-env")
    _, cfg = resolve_connection("ci")
    assert cfg.password.get_secret_value() == "from-env"


def test_delete_removes_secret(memory_secrets):
    _save("tmp", {"dialect": "postgresql", "password": "x"})
    assert client.delete("/api/connections/tmp").json() == {"ok": True}
    assert memory_secrets.data == {}
    assert client.get("/api/connections/tmp").status_code == 404


def test_bad_name_is_rejected():
    r = _save("../etc", {"dialect": "sqlite", "database": "x.db"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "CONNECTION_INVALID"


def test_test_endpoint_reports_success_and_failure(sqlite_db):
    ok = client.post("/api/connections/test", json={"type": "sql", "config": {"dialect": "sqlite", "database": sqlite_db}}).json()
    assert ok["ok"] and "1 tables" in ok["message"]
    missing_driver = client.post("/api/connections/test", json={"type": "sql", "config": {"dialect": "mysql"}}).json()
    assert not missing_driver["ok"] and "pip install" in missing_driver["message"]


def test_resources_list_tables(sqlite_db):
    _save("shop", {"dialect": "sqlite", "database": sqlite_db})
    res = client.get("/api/connections/shop/resources").json()["resources"]
    assert [(r["path"], r["kind"]) for r in res] == [("customers", "table")]


def _query_spec(connection: str, query: str = "SELECT * FROM customers ORDER BY id", limit: int = 0) -> PipelineSpec:
    return PipelineSpec(version=1, name="sql", nodes=[
        {"id": "q1", "type": "db_connector", "position": {"x": 0, "y": 0},
         "config": {"connection": connection, "query": query, "limit": limit}},
    ], edges=[])


@pytest.mark.asyncio
async def test_sql_query_node_runs_in_the_worker(sqlite_db):
    _save("shop", {"dialect": "sqlite", "database": sqlite_db})
    broker = EventBroker()
    q = broker.subscribe("sql-run")
    await exe.execute(_query_spec("shop", limit=2), "sql-run", broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    finish = next(e for e in events if e.type == "node_finish")
    assert finish.status == "success", finish.error
    assert list(finish.preview["shape"]) == [2, 2]
    assert finish.metrics["rows"] == 2


def test_sql_query_export_never_contains_credentials(memory_secrets):
    _save("prod db", {"dialect": "postgresql", "password": "hunter2"})
    code = pipeline_to_python(_query_spec("prod db"))
    assert "hunter2" not in code
    assert "os.environ['ATHENA_PROD_DB_URL']" in code
    assert "SELECT * FROM customers ORDER BY id" in code
