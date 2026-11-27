"""Dataset profiling and run-artifact endpoints (download + profile after a run)."""
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import athena.core.executor as exe
from athena.core.events import EventBroker
from athena.main import app
from athena.profiling import column_kind, profile_frame
from athena.schemas.pipeline import PipelineSpec

client = TestClient(app)
DATA_CSV = str(Path(__file__).parents[1] / "data.csv")


@pytest.fixture
def messy() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 400
    signal = rng.normal(size=n)
    df = pd.DataFrame({
        "customer_id": np.arange(n),                                   # ID-like
        "country": ["BD"] * n,                                         # constant
        "income": np.exp(rng.normal(3, 1.2, n)),                       # skewed
        "notes": [None] * 300 + ["vip"] * 100,                         # 75% missing
        "zip": [f"Z{i % 120:03d}" for i in range(n)],                  # 120 categories
        "review": [f"this product was quite good, number {i} in my list of purchases" for i in range(n)],  # text
        "signup": pd.date_range("2025-01-01", periods=n, freq="D").astype(str),  # datetime as text
        "is_member": rng.integers(0, 2, n),                            # binary
        "signal": signal,                                              # informative
        "noise": rng.normal(size=n),                                   # uninformative
    })
    df["target"] = (signal > 1.0).astype(int)                          # imbalanced (~16% positive)
    df["leak"] = df["target"] * 10 + rng.normal(0, 0.01, n)            # leaks the answer
    return pd.concat([df, df.head(8)], ignore_index=True)              # 8 duplicate rows


def test_column_kinds(messy: pd.DataFrame):
    kinds = {c: column_kind(messy[c]) for c in messy.columns}
    assert kinds == {"customer_id": "numeric", "country": "categorical", "income": "numeric", "notes": "categorical",
                     "zip": "categorical", "review": "text", "signup": "datetime", "is_member": "binary",
                     "signal": "numeric", "noise": "numeric", "target": "binary", "leak": "numeric"}


def test_profile_finds_the_data_quality_problems(messy: pd.DataFrame):
    p = profile_frame(messy)
    json.dumps(p, allow_nan=False)  # strictly JSON-safe
    codes = {(i["code"], i["column"]) for i in p["insights"]}
    assert ("constant", "country") in codes
    assert ("high_missing", "notes") in codes
    assert ("high_cardinality", "zip") in codes
    assert ("skewed", "income") in codes
    assert ("duplicates", None) in codes
    assert ("imbalance", "target") in codes
    assert ("leakage", "leak") in codes
    assert ("id_like", "customer_id") not in codes  # duplicated rows make its values repeat
    assert not any(c == "signal" for _, c in codes)  # a normal continuous feature raises nothing
    assert [i["severity"] for i in p["insights"]] == sorted((i["severity"] for i in p["insights"]), key=["warning", "info"].index)


def test_id_like_needs_unique_values():
    df = pd.DataFrame({"order_id": range(100), "amount": np.random.default_rng(1).normal(size=100)})
    codes = {(i["code"], i["column"]) for i in profile_frame(df)["insights"]}
    assert ("id_like", "order_id") in codes and ("id_like", "amount") not in codes


def test_overview_columns_and_target(messy: pd.DataFrame):
    p = profile_frame(messy)
    ov = p["overview"]
    assert ov["rows"] == 408 and ov["columns"] == 12 and ov["duplicate_rows"] == 8 and not ov["sampled"]
    income = next(c for c in p["columns"] if c["name"] == "income")
    assert income["histogram"]["counts"] and sum(income["histogram"]["counts"]) == 408
    assert len(income["histogram"]["edges"]) == len(income["histogram"]["counts"]) + 1
    zip_col = next(c for c in p["columns"] if c["name"] == "zip")
    assert len(zip_col["top"]) == 10 and zip_col["other_count"] > 0
    assert p["target"]["task"] == "classification" and {c["value"] for c in p["target"]["classes"]} == {"0", "1"}


def test_association_ranks_informative_features_first(messy: pd.DataFrame):
    ranked = [a["column"] for a in profile_frame(messy)["association"]]
    assert ranked[:2] == ["leak", "signal"] or ranked[:2] == ["signal", "leak"]
    assert ranked.index("signal") < ranked.index("noise")
    assert "country" not in ranked  # constant columns are excluded


def test_regression_target_and_explicit_target(messy: pd.DataFrame):
    p = profile_frame(messy, target="income")
    assert p["target"]["task"] == "regression" and "histogram" in p["target"]
    with pytest.raises(ValueError, match="isn't in the data"):
        profile_frame(messy, target="nope")


def test_large_frames_are_sampled():
    df = pd.DataFrame({"x": np.arange(5000), "target": np.arange(5000) % 2})
    p = profile_frame(df, max_rows=1000)
    assert p["overview"]["sampled"] and p["overview"]["profiled_rows"] == 1000 and p["overview"]["rows"] == 5000


# ---- endpoints after a real run --------------------------------------------------------------------

async def _run_classification() -> str:
    spec = PipelineSpec.model_validate({"name": "art", "nodes": [
        {"id": "n1", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": DATA_CSV}},
        {"id": "n2", "type": "train_test", "position": {"x": 1, "y": 0}, "config": {}},
        {"id": "n3", "type": "rf", "position": {"x": 2, "y": 0}, "config": {"n_estimators": 10}},
    ], "edges": [{"id": "a", "source": "n1", "target": "n2"},
                 {"id": "b", "source": "n2", "target": "n3", "source_port": 0, "target_port": 0},
                 {"id": "c", "source": "n2", "target": "n3", "source_port": 1, "target_port": 1}]})
    broker = EventBroker()
    run_id = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
    q = broker.subscribe(run_id)
    await exe.execute(spec, run_id, broker, prewarm_next=False)
    events = []
    while not q.empty():
        events.append(await q.get())
    assert events[-1].status == "completed"
    return run_id


@pytest.mark.asyncio
async def test_download_and_profile_after_a_run():
    run_id = await _run_classification()
    csv = client.get(f"/api/runs/{run_id}/artifacts/n1/0")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert pd.read_csv(io.BytesIO(csv.content)).equals(pd.read_csv(DATA_CSV))
    pq = client.get(f"/api/runs/{run_id}/artifacts/n2/0", params={"format": "parquet"})
    assert len(pd.read_parquet(io.BytesIO(pq.content))) == 240  # X_train
    model = joblib.load(io.BytesIO(client.get(f"/api/runs/{run_id}/artifacts/n3/0").content))
    assert hasattr(model, "predict")

    prof = client.get(f"/api/runs/{run_id}/profile/n1/0").json()
    assert prof["overview"]["rows"] == 300 and prof["target"]["name"] == "target"
    assert prof["overview"]["missing_cells"] == 36  # data.csv ships with 36 missing values
    assert [a["column"] for a in prof["association"]][:1] in (["feature_1"], ["feature_2"], ["feature_3"], ["feature_4"])
    assert client.get(f"/api/runs/{run_id}/profile/n3/0").status_code == 400  # a model isn't a table


def test_artifact_errors_are_clear():
    bad = client.get("/api/runs/..%2F..%2Fetc/artifacts/n1/0")
    assert bad.status_code in (404, 400)
    gone = client.get("/api/runs/0b1c2d3e-4f50-4a6b-8c7d-000000000000/artifacts/n1/0")
    assert gone.status_code == 404 and "kept until Athena restarts" in gone.json()["detail"]["detail"]
