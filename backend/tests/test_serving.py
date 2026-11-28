"""Model bundles and local prediction endpoints (a real service process per endpoint)."""
import io
import json
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from athena.config import settings
from athena.main import app
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec
from athena.serving import endpoints

client = TestClient(app)
BACKEND = Path(__file__).parents[1]


def _n(nid, ntype, **config):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config}


def _e(eid, s, t, sp=0, tp=0):
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    yield tmp_path
    endpoints.stop_all()


def _run(spec: PipelineSpec, data_dir: Path) -> str:
    run_id = str(uuid.uuid4())
    events: list[dict] = []
    assert run_spec(spec, run_id, events.append, lambda: False, data_dir / "cache" / run_id) == "completed", events[-3:]
    return run_id


def _classifier() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "churn", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("imp", "imputer", strategy="median"),
        _n("tt", "train_test"), _n("rf", "rf", n_estimators=20), _n("cal", "calibrate", cv=3),
    ], "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "rf", 0, 0), _e("d", "tt", "rf", 1, 1),
                 _e("e", "rf", "cal", 0, 0), _e("f", "tt", "cal", 0, 1), _e("g", "tt", "cal", 1, 2)]})


def _bundle(spec: PipelineSpec, run_id: str, node: str, name: str) -> dict:
    res = client.post("/api/serving/bundles", json={"name": name, "spec": spec.model_dump(), "run_id": run_id, "node_id": node})
    assert res.status_code == 200, res.text
    return res.json()


def test_bundle_contents(data_dir: Path):
    spec = _classifier()
    run_id = _run(spec, data_dir)
    b = _bundle(spec, run_id, "rf", "Churn model")
    path = Path(b["path"])
    assert b["slug"] == "churn-model" and b["task"] == "classification" and b["model"] == "RandomForestClassifier"
    assert sorted(p.name for p in path.iterdir()) == sorted(["model.joblib", "schema.json", "example.json", "requirements.txt", "service.py",
                                                              "service_bentoml.py", "bentofile.yaml", "Dockerfile", "README.md"])
    X = pd.read_csv(BACKEND / "data.csv").drop(columns=["target"])
    assert [f["name"] for f in b["features"]] == list(X.columns) and all(f["kind"] == "number" for f in b["features"])
    assert b["preprocessing_not_included"] == ["Missing Value Imputer"] and not b["needs_athena"]
    reqs = (path / "requirements.txt").read_text().splitlines()
    import sklearn
    assert f"scikit-learn=={sklearn.__version__}" in reqs and any(r.startswith("fastapi==") for r in reqs)
    compile((path / "service.py").read_text(), "service.py", "exec")
    compile((path / "service_bentoml.py").read_text(), "service_bentoml.py", "exec")
    readme = (path / "README.md").read_text()
    assert "Missing Value Imputer" in readme and "docker build -t churn-model" in readme
    example = json.loads((path / "example.json").read_text())["rows"][0]
    assert set(example) == set(X.columns)
    assert not (X == pd.Series(example)).all(axis=1).any()  # medians, not a real row from the data


def test_endpoint_serves_predictions(data_dir: Path):
    spec = _classifier()
    run_id = _run(spec, data_dir)
    b = _bundle(spec, run_id, "cal", "calibrated")  # follows calibrate -> rf -> X_train for the schema
    started = client.post(f"/api/serving/endpoints/{b['slug']}").json()
    assert started["running"] and started["url"].startswith("http://127.0.0.1:")
    example = json.loads((Path(b["path"]) / "example.json").read_text())
    ok = client.post(f"/api/serving/endpoints/{b['slug']}/predict", json={"rows": example["rows"] * 3}).json()
    assert ok["status"] == 200 and len(ok["response"]["predictions"]) == 3
    probs = ok["response"]["probabilities"][0]
    assert set(probs) == {str(c) for c in b["classes"]} and abs(sum(probs.values()) - 1) < 1e-6
    row = dict(example["rows"][0])
    row.pop(next(iter(row)))
    bad = client.post(f"/api/serving/endpoints/{b['slug']}/predict", json={"rows": [row]}).json()
    assert bad["status"] == 422 and "Missing feature" in bad["response"]["detail"]
    listed = client.get("/api/serving/bundles").json()["bundles"]
    assert listed[0]["endpoint"]["running"]
    assert client.delete(f"/api/serving/endpoints/{b['slug']}").status_code == 200
    assert client.post(f"/api/serving/endpoints/{b['slug']}/predict", json={"rows": [row]}).status_code == 409


def test_regression_download_and_delete(data_dir: Path):
    spec = PipelineSpec.model_validate({"name": "reg", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "regression_data.csv")), _n("imp", "imputer"), _n("tt", "train_test", stratify=False),
        _n("lr", "lin_reg")], "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "lr", 0, 0), _e("d", "tt", "lr", 1, 1)]})
    b = _bundle(spec, _run(spec, data_dir), "lr", "prices")
    assert b["task"] == "regression"
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/serving/bundles/prices/download").content))
    assert "prices/service.py" in z.namelist() and "prices/model.joblib" in z.namelist()
    assert client.delete("/api/serving/bundles/prices").status_code == 200
    assert client.get("/api/serving/bundles").json()["bundles"] == []


def test_models_built_by_athena_wrappers_say_so(data_dir: Path):
    spec = PipelineSpec.model_validate({"name": "sm", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("imp", "imputer"), _n("tt", "train_test"), _n("lg", "sm_logit")],
        "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "lg", 0, 0), _e("d", "tt", "lg", 1, 1)]})
    b = _bundle(spec, _run(spec, data_dir), "lg", "logit")
    assert b["needs_athena"] and "pip install athena-backend" in (Path(b["path"]) / "README.md").read_text()


def test_errors(data_dir: Path):
    spec = _classifier()
    run_id = _run(spec, data_dir)
    def post(**kw):
        return client.post("/api/serving/bundles", json={"name": "x", "spec": spec.model_dump(), "run_id": run_id, "node_id": "rf", **kw})
    assert post(node_id="imp").json()["detail"]["code"] == "BUNDLE_FAILED"  # a table can't predict
    assert post(name="  ").json()["detail"]["detail"] == "Give the model a name"
    assert post(run_id=str(uuid.uuid4())).status_code == 404
    assert client.post("/api/serving/endpoints/nope").status_code == 404


def test_endpoint_exits_when_athena_goes_away(data_dir: Path):
    """The service watches its stdin pipe: closing it (what happens when Athena dies) stops the service."""
    import time
    spec = _classifier()
    b = _bundle(spec, _run(spec, data_dir), "rf", "watchdog")
    client.post(f"/api/serving/endpoints/{b['slug']}")
    ep = endpoints._ENDPOINTS[b["slug"]]
    ep.process.stdin.close()  # simulate the parent vanishing
    for _ in range(50):
        if not ep.alive():
            break
        time.sleep(0.2)
    assert not ep.alive()
    assert not endpoints.status(b["slug"])["running"]
