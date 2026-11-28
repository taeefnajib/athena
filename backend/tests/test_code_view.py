"""POST /api/pipelines/code: the per-node code the inspector shows is exactly what Export Code writes."""
from pathlib import Path

from fastapi.testclient import TestClient

from athena.main import app

client = TestClient(app)
DATA = str(Path(__file__).parents[1] / "data.csv")


def _spec(extra_nodes=(), extra_edges=()):
    return {"name": "code", "nodes": [
        {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": DATA}},
        {"id": "n2", "type": "imputer", "position": {"x": 0, "y": 0}, "config": {"strategy": "median"}},
        {"id": "n3", "type": "train_test", "position": {"x": 0, "y": 0}, "config": {}},
        *extra_nodes,
    ], "edges": [{"id": "a", "source": "n1", "target": "n2"}, {"id": "b", "source": "n2", "target": "n3"}, *extra_edges]}


def test_sections_match_the_exported_script():
    body = client.post("/api/pipelines/code", json={"spec": _spec(), "format": "python"}).json()
    by_id = {s["node_id"]: s for s in body["sections"]}
    assert [s["node_id"] for s in body["sections"]] == ["n1", "n2", "n3"]  # topological order
    assert "df_n2" in by_id["n2"]["code"] and "df_n1" in by_id["n2"]["code"]  # variables follow the edges
    assert any("SimpleImputer" in i for i in by_id["n2"]["imports"])
    for s in body["sections"]:
        assert s["exported"] and s["code"] in body["script"]


def test_unconnected_and_unexportable_nodes_explain_themselves():
    model = {"id": "m", "type": "rf", "position": {"x": 0, "y": 0}, "config": {}}
    body = client.post("/api/pipelines/code", json={"spec": _spec([model]), "format": "python"}).json()
    rf = next(s for s in body["sections"] if s["node_id"] == "m")
    assert not rf["exported"] and "isn't connected" in rf["code"]
