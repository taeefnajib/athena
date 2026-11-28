"""Subflows: expansion before run/export, identical results to the flat pipeline, the library API."""
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from athena.config import settings
from athena.core.codegen import pipeline_to_python
from athena.core.subflows import expand
from athena.main import app
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec

client = TestClient(app)
DATA = str(Path(__file__).parents[1] / "data.csv")


def _n(nid: str, ntype: str, **config) -> dict:
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config}


def _e(eid: str, s: str, t: str, sp: int = 0, tp: int = 0) -> dict:
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


PREP = {  # imputer -> scaler, exposed as dataset in / dataset out
    "name": "Clean & scale",
    "nodes": [_n("imp", "imputer", strategy="median"), _n("sc", "scaler", method="MinMaxScaler")],
    "edges": [_e("i1", "imp", "sc")],
    "inputs": [{"name": "dataset", "type": "dataset", "node": "imp", "port": 0}],
    "outputs": [{"name": "dataset", "type": "dataset", "node": "sc", "port": 0}],
}


def _with_subflow() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "sf", "nodes": [
        _n("csv", "csv_loader", path=DATA), _n("prep", "subflow", **PREP), _n("tt", "train_test"), _n("info", "df_info"),
    ], "edges": [_e("a", "csv", "prep"), _e("b", "prep", "tt"), _e("c", "prep", "info")]})


def _flat() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "flat", "nodes": [
        _n("csv", "csv_loader", path=DATA), _n("imp", "imputer", strategy="median"), _n("sc", "scaler", method="MinMaxScaler"),
        _n("tt", "train_test"), _n("info", "df_info"),
    ], "edges": [_e("a", "csv", "imp"), _e("i1", "imp", "sc"), _e("b", "sc", "tt"), _e("c", "sc", "info")]})


def test_expand_rewires_the_boundary():
    spec, start = expand(_with_subflow(), ["prep"])
    ids = [n.id for n in spec.nodes]
    assert ids == ["csv", "prep.imp", "prep.sc", "tt", "info"] and start == ["prep.imp", "prep.sc"]
    edges = {(e.source, e.target) for e in spec.edges}
    assert edges == {("csv", "prep.imp"), ("prep.imp", "prep.sc"), ("prep.sc", "tt"), ("prep.sc", "info")}
    assert expand(_flat(), ["imp"]) == (_flat(), ["imp"])  # no subflows: untouched


def test_nested_subflows_expand_fully():
    outer = {"name": "outer", "nodes": [_n("inner", "subflow", **PREP)], "edges": [],
             "inputs": [{"name": "dataset", "type": "dataset", "node": "inner", "port": 0}],
             "outputs": [{"name": "dataset", "type": "dataset", "node": "inner", "port": 0}]}
    spec = PipelineSpec.model_validate({"name": "n", "nodes": [_n("csv", "csv_loader", path=DATA), _n("o", "subflow", **outer)],
                                        "edges": [_e("a", "csv", "o")]})
    flat, start = expand(spec, ["o"])
    assert [n.id for n in flat.nodes] == ["csv", "o.inner.imp", "o.inner.sc"] and start == ["o.inner.imp", "o.inner.sc"]
    assert {(e.source, e.target) for e in flat.edges} == {("csv", "o.inner.imp"), ("o.inner.imp", "o.inner.sc")}


def test_results_match_the_flat_pipeline(tmp_path: Path):
    def outputs(spec: PipelineSpec, sub: str) -> dict:
        arts: dict = {}
        events: list[dict] = []
        assert run_spec(spec, "r", events.append, lambda: False, tmp_path / sub, artifacts_out=arts) == "completed"
        return arts
    a, b = outputs(_with_subflow(), "a"), outputs(_flat(), "b")
    pd.testing.assert_frame_equal(a[("prep.sc", 0)], b[("sc", 0)])
    pd.testing.assert_frame_equal(a[("tt", 0)], b[("tt", 0)])  # X_train downstream of the subflow


def test_export_flattens_subflows():
    code = pipeline_to_python(_with_subflow())
    assert "# --- Node prep.imp: Missing Value Imputer ---" in code and "df_prep_sc" in code and "Not exported" not in code


@pytest.mark.parametrize(("bad", "message"), [
    ({"outputs": []}, "has no output port 0"),
    ({"inputs": [{"name": "x", "type": "dataset", "node": "ghost", "port": 0}]}, "missing node 'ghost'"),
    ({"edges": [_e("z", "imp", "elsewhere")]}, "points outside the subflow"),
])
def test_bad_subflows_are_clear_errors(bad: dict, message: str):
    spec = _with_subflow()
    spec.nodes[1].config = {**PREP, **bad}
    with pytest.raises(ValueError, match=message):
        expand(spec)
    res = client.post("/api/pipelines/run", json={"spec": spec.model_dump()})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "SUBFLOW_INVALID"


def test_code_endpoint_lists_inner_sections():
    body = client.post("/api/pipelines/code", json={"spec": _with_subflow().model_dump(), "format": "python"}).json()
    assert [s["node_id"] for s in body["sections"]] == ["csv", "prep.imp", "prep.sc", "tt", "info"]


def test_library_save_list_delete(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first = client.put("/api/subflows", json={"config": PREP}).json()
    assert first["replaced"] is False and client.put("/api/subflows", json={"config": PREP}).json()["replaced"] is True
    listed = client.get("/api/subflows").json()["subflows"]
    assert [(s["name"], s["nodes"], s["inputs"], s["outputs"]) for s in listed] == [("Clean & scale", 2, ["dataset"], ["dataset"])]
    assert listed[0]["config"]["nodes"][0]["type"] == "imputer"
    assert client.put("/api/subflows", json={"config": {**PREP, "name": "  "}}).json()["detail"]["code"] == "SUBFLOW_INVALID"
    assert client.put("/api/subflows", json={"config": {**PREP, "nodes": []}}).status_code == 400
    assert client.delete("/api/subflows/Clean & scale").status_code == 200
    assert client.get("/api/subflows").json()["subflows"] == []
    assert client.delete("/api/subflows/nope").status_code == 404
