"""Parquet Loader, SQL Transform (DuckDB), the Object Storage connector and the Cloud File Loader."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest
import structlog
from fastapi.testclient import TestClient

from athena.connectors import secrets
from athena.core.codegen import pipeline_to_python
from athena.core.handler import ExecutionContext
from athena.main import app
from athena.nodes.files import CloudFileLoader, DuckDbSql, ParquetLoader
from athena.schemas.pipeline import PipelineSpec

client = TestClient(app)


@pytest.fixture(autouse=True)
def memory_secrets():
    old = secrets.get_store()
    secrets.set_store(secrets.MemoryStore())
    yield
    secrets.set_store(old)


def _ctx(config: dict, inputs: list | None = None, tmp: Path | None = None) -> ExecutionContext:
    return ExecutionContext(node_id="x1", node_type="t", config=config, inputs=inputs or [], run_id="r",
                            cache_dir=tmp or Path("."), logger=structlog.get_logger())


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    """A small 'bucket': a CSV, a JSON Lines file and a partitioned Parquet folder."""
    root = tmp_path / "lake"
    (root / "sales").mkdir(parents=True)
    pd.DataFrame({"id": [1, 2, 3], "country": ["BD", "DE", "BD"]}).to_csv(root / "customers.csv", index=False)
    pd.DataFrame({"id": [1, 2], "event": ["click", "buy"]}).to_json(root / "events.jsonl", orient="records", lines=True)
    for month, rows in (("01", 4), ("02", 6)):
        pd.DataFrame({"month": [month] * rows, "amount": range(rows)}).to_parquet(root / "sales" / f"2026-{month}.parquet")
    return root


# ---- Parquet Loader ------------------------------------------------------------------------------

def test_parquet_file_folder_and_columns(lake: Path):
    one = ParquetLoader()(_ctx({"path": str(lake / "sales" / "2026-01.parquet")})).outputs[0]
    assert len(one) == 4
    folder = ParquetLoader()(_ctx({"path": str(lake / "sales"), "columns": "amount"})).outputs[0]
    assert list(folder.columns) == ["amount"] and len(folder) == 10


def test_parquet_missing_file_is_a_clear_error(tmp_path: Path):
    with pytest.raises(ValueError, match="not found|Couldn't read"):
        ParquetLoader()(_ctx({"path": str(tmp_path / "nope.parquet")}))


# ---- SQL Transform -------------------------------------------------------------------------------

def test_sql_joins_two_inputs():
    customers = pd.DataFrame({"id": [1, 2, 3], "country": ["BD", "DE", "BD"]})
    orders = pd.DataFrame({"customer_id": [1, 1, 3, 2], "amount": [10, 5, 7, 1]})
    q = "SELECT c.country, SUM(o.amount) AS revenue FROM in1 c JOIN in2 o ON o.customer_id = c.id GROUP BY 1 ORDER BY 1"
    out = DuckDbSql()(_ctx({"query": q}, [customers, orders])).outputs[0]
    assert out.to_dict("records") == [{"country": "BD", "revenue": 22}, {"country": "DE", "revenue": 1}]


def test_sql_reads_files_directly(lake: Path):
    glob = str(lake / "sales" / "*.parquet").replace("\\", "/")
    out = DuckDbSql()(_ctx({"query": f"SELECT month, COUNT(*) AS n FROM '{glob}' GROUP BY 1 ORDER BY 1"})).outputs[0]
    assert out["n"].tolist() == [4, 6]


def test_sql_error_is_readable():
    with pytest.raises(ValueError, match="SQL error"):
        DuckDbSql()(_ctx({"query": "SELECT nope FROM in1"}, [pd.DataFrame({"a": [1]})]))


# ---- Object Storage connector --------------------------------------------------------------------

def _save_local(lake: Path, name: str = "lake") -> None:
    r = client.put("/api/connections", json={"name": name, "type": "storage",
                                              "config": {"protocol": "local", "bucket": str(lake)}})
    assert r.status_code == 200, r.text


def test_storage_test_and_browse(lake: Path):
    ok = client.post("/api/connections/test", json={"type": "storage", "config": {"protocol": "local", "bucket": str(lake)}}).json()
    assert ok["ok"] and "3 items" in ok["message"]
    _save_local(lake)
    top = client.get("/api/connections/lake/resources").json()["resources"]
    assert [(r["name"], r["kind"]) for r in top] == [("sales", "folder"), ("customers.csv", "file"), ("events.jsonl", "file")]
    inside = client.get("/api/connections/lake/resources", params={"path": "sales"}).json()["resources"]
    assert {r["name"] for r in inside} == {"2026-01.parquet", "2026-02.parquet"}


@pytest.mark.skipif(importlib.util.find_spec("s3fs") is not None, reason="s3fs is installed")
def test_missing_cloud_driver_says_how_to_install():
    r = client.post("/api/connections/test", json={"type": "storage", "config": {"protocol": "s3", "bucket": "b"}}).json()
    assert not r["ok"] and "athena-backend[s3]" in r["message"]


@pytest.mark.parametrize(("path", "rows", "cols"), [
    ("customers.csv", 3, ["id", "country"]),
    ("events.jsonl", 2, ["id", "event"]),
    ("sales", 10, ["month", "amount"]),             # a folder is read as one Parquet dataset
    ("sales/*.parquet", 10, ["month", "amount"]),   # a glob concatenates matching files
])
def test_cloud_file_loader_reads_each_format(lake: Path, path: str, rows: int, cols: list[str]):
    _save_local(lake)
    result = CloudFileLoader()(_ctx({"connection": "lake", "path": path}))
    df = result.outputs[0]
    assert len(df) == rows and list(df.columns) == cols


def test_cloud_file_loader_export_has_no_credentials(lake: Path):
    client.put("/api/connections", json={"name": "minio", "type": "storage", "config": {
        "protocol": "s3", "bucket": "datalake", "prefix": "raw", "endpoint_url": "http://localhost:9000",
        "access_key_id": "AKIA-TEST", "secret_access_key": "super-secret"}})
    spec = PipelineSpec.model_validate({"nodes": [{"id": "c1", "type": "storage_loader", "position": {"x": 0, "y": 0},
                                                   "config": {"connection": "minio", "path": "orders.parquet"}}], "edges": []})
    code = pipeline_to_python(spec)
    assert "pd.read_parquet('s3://datalake/raw/orders.parquet'" in code
    assert "'endpoint_url': 'http://localhost:9000'" in code
    assert "super-secret" not in code and "AKIA-TEST" not in code


def test_sql_transform_export():
    spec = PipelineSpec.model_validate({"nodes": [
        {"id": "a", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": "a.csv"}},
        {"id": "s", "type": "duckdb_sql", "position": {"x": 1, "y": 0}, "config": {"query": "SELECT * FROM in1"}},
    ], "edges": [{"id": "e", "source": "a", "target": "s"}]})
    code = pipeline_to_python(spec)
    assert "in1 = df_a" in code and "duckdb.sql('SELECT * FROM in1').df()" in code
