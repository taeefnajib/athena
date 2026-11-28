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
    assert sorted(p.name for p in path.iterdir()) == sorted(["model.joblib", "preprocessing.joblib", "preprocess.py", "schema.json", "example.json", "MODEL_CARD.md",
                                                              "requirements.txt", "service.py", "service_bentoml.py", "bentofile.yaml", "Dockerfile", "README.md"])
    X = pd.read_csv(BACKEND / "data.csv").drop(columns=["target"])
    assert [f["name"] for f in b["features"]] == list(X.columns) and all(f["kind"] == "number" for f in b["features"])
    assert b["preprocessing_replayed"] == ["Missing Value Imputer"] and b["preprocessing_not_included"] == [] and b["preprocessing_verified"]
    assert not b["needs_athena"]
    reqs = (path / "requirements.txt").read_text().splitlines()
    import sklearn
    assert f"scikit-learn=={sklearn.__version__}" in reqs and any(r.startswith("fastapi==") for r in reqs)
    compile((path / "service.py").read_text(), "service.py", "exec")
    compile((path / "service_bentoml.py").read_text(), "service_bentoml.py", "exec")
    readme = (path / "README.md").read_text()
    assert "raw rows" in readme and "Missing Value Imputer" in readme and "docker build -t churn-model" in readme
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


def _messy_csv(tmp: Path) -> Path:
    """Missing values, a text category, a date: what a real export looks like."""
    import numpy as np
    rng = np.random.default_rng(0)
    n = 240
    df = pd.DataFrame({
        "age": rng.normal(40, 10, n).round(), "income": rng.normal(50, 15, n),
        "plan": rng.choice(["basic", "plus", "pro"], n), "signup": pd.date_range("2024-01-01", periods=n, freq="D").astype(str),
    })
    df.loc[::17, "income"] = np.nan
    df["target"] = ((df["income"].fillna(50) > 52) | (df["plan"] == "pro")).astype(int)
    path = tmp / "messy.csv"
    df.to_csv(path, index=False)
    return path


def _messy_spec(csv: Path, extra_nodes=(), extra_edges=(), first="imp") -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "messy", "nodes": [
        _n("csv", "csv_loader", path=str(csv)), _n("imp", "imputer", strategy="median"),
        _n("dates", "date_feat", col="signup", features="month,weekday"), _n("ohe", "ohe", cols="plan"),
        _n("sc", "scaler", method="RobustScaler"), _n("sel", "col_selector", mode="exclude", cols="signup"),
        _n("tt", "train_test", stratify=True), _n("rf", "rf", n_estimators=25), *extra_nodes,
    ], "edges": [_e("a", "csv", first), _e("b", "imp", "dates"), _e("c", "dates", "ohe"), _e("d", "ohe", "sc"),
                 _e("e", "sc", "sel"), _e("f", "sel", "tt"), _e("g", "tt", "rf", 0, 0), _e("h", "tt", "rf", 1, 1), *extra_edges]})


def test_replayed_preprocessing_reproduces_the_test_set_exactly(data_dir: Path):
    """The bundle's preprocessing, run on the raw CSV rows of the test split, must give the pipeline's X_test."""
    import joblib

    from athena.core.artifacts import load_output
    from athena.serving import replay_core
    csv = _messy_csv(data_dir)
    spec = _messy_spec(csv)
    run_id = _run(spec, data_dir)
    b = _bundle(spec, run_id, "rf", "messy")
    assert b["preprocessing_verified"] and b["preprocessing_not_included"] == []
    assert b["preprocessing_replayed"] == ["Missing Value Imputer", "Date Feature Extractor", "One-Hot Encoder", "Scaler", "Column Selector"]
    assert [f["name"] for f in b["features"]] == ["age", "income", "plan", "signup"]  # raw columns, no target
    steps = joblib.load(Path(b["path"]) / "preprocessing.joblib")
    X_test = load_output(run_id, "tt", 2)
    raw = pd.read_csv(csv).drop(columns=["target"]).loc[X_test.index]
    pd.testing.assert_frame_equal(replay_core.apply(steps, raw), X_test, check_dtype=False)

    assert client.post(f"/api/serving/endpoints/{b['slug']}").json()["running"]
    raw_row = {"age": 35, "income": None, "plan": "pro", "signup": "2024-03-05"}  # a missing value and a category, as raw data
    res = client.post(f"/api/serving/endpoints/{b['slug']}/predict", json={"rows": [raw_row, {**raw_row, "plan": "enterprise"}]}).json()
    assert res["status"] == 200 and len(res["response"]["predictions"]) == 2  # an unseen category encodes as all-zero, like training
    bad = client.post(f"/api/serving/endpoints/{b['slug']}/predict", json={"rows": [{**raw_row, "age": "old"}]}).json()
    assert bad["status"] == 422


def test_unsupported_step_cuts_the_chain(data_dir: Path):
    csv = _messy_csv(data_dir)
    split = _n("split", "validator")  # passes the data through but records no replay step
    spec = _messy_spec(csv, extra_nodes=[split], extra_edges=[_e("z", "split", "imp")], first="split")
    b = _bundle(spec, _run(spec, data_dir), "rf", "cut")
    assert "Data Validator" in b["preprocessing_not_included"]
    assert b["preprocessing_replayed"] == ["Missing Value Imputer", "Date Feature Extractor", "One-Hot Encoder", "Scaler", "Column Selector"]
    assert b["preprocessing_verified"]


def test_a_replay_that_does_not_reproduce_training_is_dropped(data_dir: Path, monkeypatch):
    from athena.serving import chain
    real = chain.replay_core.apply

    def wrong(steps, df):  # a deliberately wrong replay: shifts every number
        out = real(steps, df)
        return out + 1.0

    monkeypatch.setattr(chain.replay_core, "apply", wrong)
    csv = _messy_csv(data_dir)
    spec = _messy_spec(csv)
    b = _bundle(spec, _run(spec, data_dir), "rf", "wrong")
    assert not b["preprocessing_verified"] and b["preprocessing_replayed"] == []
    assert "Scaler" in b["preprocessing_not_included"] and "didn't reproduce" in b["preprocessing_note"]
    assert "plan_pro" in [f["name"] for f in b["features"]]  # back to model-ready features


def _coded_csv(tmp: Path) -> Path:
    """A code column to split ("A-17"), a few extreme incomes, an id to join on."""
    import numpy as np
    rng = np.random.default_rng(1)
    n = 240
    df = pd.DataFrame({"id": np.arange(n), "age": rng.normal(40, 10, n).round(), "income": rng.normal(50, 15, n),
                       "spend": rng.normal(20, 5, n), "plan": rng.choice(["basic", "plus", "pro"], n),
                       "code": [f"{rng.choice(list('ABC'))}-{rng.integers(1, 99)}" for _ in range(n)]})
    df.loc[::29, "income"] = 400.0  # outliers
    df.loc[::17, "spend"] = np.nan
    df["target"] = ((df["income"] > 52) | (df["plan"] == "pro")).astype(int)
    path = tmp / "coded.csv"
    df.to_csv(path, index=False)
    return path


def _replay_matches_test_set(b: dict, run_id: str, raw: pd.DataFrame) -> None:
    import joblib

    from athena.core.artifacts import load_output
    from athena.serving import replay_core
    steps = joblib.load(Path(b["path"]) / "preprocessing.joblib")
    X_test = load_output(run_id, "tt", 2)
    pd.testing.assert_frame_equal(replay_core.apply(steps, raw.loc[X_test.index]), X_test, check_dtype=False)


@pytest.mark.parametrize("method", ["IQR", "Z-Score", "Isolation Forest"])
def test_outliers_string_split_and_feature_selection_are_replayed(data_dir: Path, method: str):
    csv = _coded_csv(data_dir)
    spec = PipelineSpec.model_validate({"name": "more", "nodes": [
        _n("csv", "csv_loader", path=str(csv)), _n("split", "str_split", col="code", sep="hyphen", prefix="code"),
        _n("imp", "imputer", strategy="median"), _n("flag", "outlier", method=method, action="flag", cols="income,spend"),
        _n("clip", "outlier", action="clip", cols="income"), _n("ohe", "ohe", cols="plan,code_0"),
        _n("sel", "col_selector", mode="exclude", cols="code,code_1,id"), _n("fs", "feat_imp_sel", k=5),
        _n("tt", "train_test"), _n("rf", "rf", n_estimators=20),
    ], "edges": [_e("a", "csv", "split"), _e("b", "split", "imp"), _e("c", "imp", "flag"), _e("d", "flag", "clip"),
                 _e("e", "clip", "ohe"), _e("f", "ohe", "sel"), _e("g", "sel", "fs"), _e("h", "fs", "tt"),
                 _e("i", "tt", "rf", 0, 0), _e("j", "tt", "rf", 1, 1)]})
    run_id = _run(spec, data_dir)
    b = _bundle(spec, run_id, "rf", f"more-{method}")
    assert b["preprocessing_verified"] and b["preprocessing_not_included"] == [], b["preprocessing_note"]
    assert b["preprocessing_replayed"] == ["String Splitter", "Missing Value Imputer", "Outlier Detector", "Outlier Detector",
                                           "One-Hot Encoder", "Column Selector", "Feature Importance Sel"]
    _replay_matches_test_set(b, run_id, pd.read_csv(csv).drop(columns=["target"]))


def test_a_merge_is_replayed_as_a_lookup(data_dir: Path):
    import numpy as np
    csv = _coded_csv(data_dir)
    regions = data_dir / "regions.csv"
    pd.DataFrame({"id": np.arange(240), "region": np.random.default_rng(2).choice(["north", "south"], 240),
                  "tenure": np.arange(240) % 13}).to_csv(regions, index=False)

    def spec(how: str) -> PipelineSpec:
        return PipelineSpec.model_validate({"name": "joined", "nodes": [
            _n("csv", "csv_loader", path=str(csv)), _n("reg", "csv_loader", path=str(regions)), _n("join", "data_merge", on="id", how=how),
            _n("imp", "imputer", strategy="median"), _n("ohe", "ohe", cols="plan,region"),
            _n("sel", "col_selector", mode="exclude", cols="code,id"), _n("tt", "train_test"), _n("rf", "rf", n_estimators=20),
        ], "edges": [_e("a", "csv", "join", 0, 0), _e("b", "reg", "join", 0, 1), _e("c", "join", "imp"), _e("d", "imp", "ohe"),
                     _e("e", "ohe", "sel"), _e("f", "sel", "tt"), _e("g", "tt", "rf", 0, 0), _e("h", "tt", "rf", 1, 1)]})

    s = spec("inner")
    run_id = _run(s, data_dir)
    b = _bundle(s, run_id, "rf", "joined")
    assert b["preprocessing_verified"], b["preprocessing_note"]
    assert b["preprocessing_replayed"][0] == "Data Merge / Join (joins each request with the 240-row right table saved with the model)"
    assert "region" not in [f["name"] for f in b["features"]] and "id" in [f["name"] for f in b["features"]]  # requests send the left side
    _replay_matches_test_set(b, run_id, pd.read_csv(csv).drop(columns=["target"]))

    assert client.post(f"/api/serving/endpoints/{b['slug']}").json()["running"]
    row = {"id": 7, "age": 30, "income": 60.0, "spend": 18.0, "plan": "basic", "code": "A-3"}
    ok = client.post(f"/api/serving/endpoints/{b['slug']}/predict", json={"rows": [row, {**row, "id": 9999}]}).json()
    assert ok["status"] == 200 and len(ok["response"]["predictions"]) == 2  # an unknown id still gets a prediction

    s = spec("outer")  # an outer join adds rows: not a lookup, so the chain stops there
    b = _bundle(s, _run(s, data_dir), "rf", "outer")
    assert "Data Merge / Join" not in " ".join(b["preprocessing_replayed"]) and b["preprocessing_replayed"] == ["Missing Value Imputer", "One-Hot Encoder", "Column Selector"]


def test_batch_predict_node_matches_the_bundles_batch_mode(data_dir: Path):
    """Batch Predict (in a pipeline) and `python service.py --predict-file` (outside Athena) score a raw file identically."""
    import subprocess
    import sys

    from athena.nodes.batch import _athena_bundle_predict
    csv = _messy_csv(data_dir)
    spec = _messy_spec(csv)
    b = _bundle(spec, _run(spec, data_dir), "rf", "Batch churn")
    raw = pd.read_csv(csv).drop(columns=["target"]).head(60)
    raw.loc[3, "income"] = None  # raw data, missing values included
    src, dst = data_dir / "new_rows.csv", data_dir / "scored.parquet"
    raw.to_csv(src, index=False)

    scoring = PipelineSpec.model_validate({"name": "score", "nodes": [
        _n("new", "csv_loader", path=str(src)), _n("bp", "batch_predict", model="Batch churn")],
        "edges": [_e("a", "new", "bp")]})
    events: list[dict] = []
    artifacts: dict = {}
    assert run_spec(scoring, "batch", events.append, lambda: False, data_dir / "cache" / "batch", artifacts_out=artifacts) == "completed"
    node_out = artifacts[("bp", 0)]
    assert list(node_out.columns) == [*raw.columns, "prediction", "proba_0", "proba_1"] and len(node_out) == 60
    finish = next(e for e in events if e["type"] == "node_finish" and e["node_id"] == "bp")
    assert finish["metrics"]["rows"] == 60 and finish["metrics"]["predicted_0"] + finish["metrics"]["predicted_1"] == 60

    done = subprocess.run([sys.executable, "service.py", "--predict-file", str(src), "--output", str(dst)],
                          cwd=b["path"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert "Scored 60 row(s)" in done.stdout
    pd.testing.assert_frame_equal(pd.read_parquet(dst), node_out.reset_index(drop=True), check_dtype=False)

    lean = _athena_bundle_predict(b["path"], raw, probabilities=False, keep_columns=False)
    assert list(lean.columns) == ["prediction"]
    with pytest.raises(ValueError, match="Missing feature"):
        _athena_bundle_predict(b["path"], raw.drop(columns=["plan"]))
    bad = subprocess.run([sys.executable, "service.py", "--predict-file", str(data_dir / "nope.csv")], cwd=b["path"], capture_output=True, text=True, timeout=120)
    assert bad.returncode == 1 and "error:" in bad.stderr

    unknown = PipelineSpec.model_validate({"name": "x", "nodes": [_n("new", "csv_loader", path=str(src)), _n("bp", "batch_predict", model="nope")],
                                           "edges": [_e("a", "new", "bp")]})
    events = []
    assert run_spec(unknown, "unknown", events.append, lambda: False, data_dir / "cache" / "unknown") == "error"
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]["message"]
    assert "No packaged model named 'nope'" in err and "batch-churn" in err
