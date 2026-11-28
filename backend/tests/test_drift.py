"""Evidently monitoring nodes: data drift, prediction drift, data quality, and their HTML reports."""
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from scipy import stats
from sklearn.linear_model import LinearRegression, LogisticRegression

pytest.importorskip("evidently")

from athena.config import settings
from athena.main import app
from athena.nodes.drift import (
    EvidentlyDriftHandler,
    _athena_data_quality,
    _athena_evidently_drift,
    _athena_prediction_drift,
)
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec
from tests.test_gates import _ctx, _e, _n

client = TestClient(app)


def frames(n_ref: int = 500, n_cur: int = 400, shift: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """'a' shifts and 'c' changes its mix in the current table; 'b' and 'k' don't."""
    rng = np.random.default_rng(0)
    ref = pd.DataFrame({"a": rng.normal(0, 1, n_ref), "b": rng.normal(5, 2, n_ref),
                        "c": rng.choice(["x", "y", "z"], n_ref), "k": rng.integers(0, 3, n_ref)})
    cur = pd.DataFrame({"a": rng.normal(shift, 1, n_cur), "b": rng.normal(5, 2, n_cur),
                        "c": rng.choice(["x", "y", "z"], n_cur, p=[.7, .2, .1]), "k": rng.integers(0, 3, n_cur)})
    return ref, cur


def test_drift_flags_the_columns_that_moved():
    ref, cur = frames()
    report, table, _ = _athena_evidently_drift(cur, ref)
    by = table.set_index("column")
    assert by["drifted"].to_dict() == {"a": True, "b": False, "c": True, "k": False}
    assert report["drifted_columns"] == 2 and report["columns_checked"] == 4 and report["share_drifted"] == 0.5
    assert report["dataset_drift"] == 1.0  # half the columns drifted: at the default drift share
    # small numeric samples default to the two-sample K-S test: its p-value is the score
    assert by.loc["a", "method"] == "K-S p_value" and by.loc["b", "score"] == pytest.approx(stats.ks_2samp(ref["b"], cur["b"]).pvalue, rel=1e-9)
    assert report["drift_score.b"] == by.loc["b", "score"]
    counts = pd.crosstab(pd.concat([ref["c"], cur["c"]]), ["ref"] * len(ref) + ["cur"] * len(cur))
    assert by.loc["c", "method"] == "chi-square p_value"
    assert by.loc["c", "score"] < 1e-10 and stats.chi2_contingency(counts).pvalue < 1e-10


def test_drift_methods_thresholds_and_columns():
    ref, cur = frames()
    report, table, _ = _athena_evidently_drift(cur, ref, "a, b", num_method="wasserstein", num_threshold=0.5, drift_share=0.9)
    assert table["column"].tolist() == ["a", "b"] and set(table["threshold"]) == {0.5}
    assert table.set_index("column")["drifted"].to_dict() == {"a": True, "b": False}  # distances: drift is a score above it
    assert report["dataset_drift"] == 0.0
    _, table, _ = _athena_evidently_drift(cur, ref, "c", cat_method="jensenshannon")
    assert table.iloc[0]["method"].lower().startswith("jensen")
    with pytest.raises(ValueError, match="must be in both tables"):
        _athena_evidently_drift(cur, ref, "a, nope")
    with pytest.raises(ValueError, match="no columns in common"):
        _athena_evidently_drift(cur.rename(columns=str.upper), ref)


def test_no_drift_between_samples_of_the_same_data():
    ref, _ = frames()
    report, table, _ = _athena_evidently_drift(ref.iloc[250:], ref.iloc[:250])
    assert report["drifted_columns"] == 0 and report["dataset_drift"] == 0.0 and not table["drifted"].any()


def test_handler_returns_report_table_and_the_html_report():
    ref, cur = frames()
    res = EvidentlyDriftHandler()(_ctx({}, [cur, ref]))
    report, table = res.outputs
    assert res.metrics == {"dataset_drift": 1.0, "drifted_columns": 2.0, "columns_checked": 4.0, "share_drifted": 0.5}
    assert list(res.documents) == ["report.html"] and "<html" in res.documents["report.html"].lower()
    assert res.preview.kind == "dataframe" and len(table) == 4 and report["drifted_columns"] == 2


def test_prediction_drift():
    ref, cur = frames(shift=1.5)
    y = (ref["a"] + ref["b"] > 5).astype(int)
    clf = LogisticRegression().fit(ref[["a", "b"]], y)
    report, table, _ = _athena_prediction_drift(clf, ref, cur)  # extra columns are ignored: the model names its features
    assert report["prediction_drift"] == 1.0 and report["probability_drift"] == 1.0
    assert table["column"].tolist() == ["prediction", "probability"]
    same = ref.sample(frac=1, random_state=5)  # two halves of the same data
    stable, _, _ = _athena_prediction_drift(clf, same.iloc[:250], same.iloc[250:])
    assert stable["prediction_drift"] == 0.0 and stable["probability_drift"] == 0.0
    proba = clf.predict_proba(same[["a", "b"]])[:, 1]
    assert stable["probability_drift_score"] == pytest.approx(stats.ks_2samp(proba[250:], proba[:250]).pvalue, rel=1e-9)
    reg = LinearRegression().fit(ref[["b"]], ref["a"])  # regression: a numeric prediction, no probability
    r, t, _ = _athena_prediction_drift(reg, ref, cur)
    assert "probability_drift" not in r and t["column"].tolist() == ["prediction"]
    with pytest.raises(ValueError, match="lacks the model's feature"):
        _athena_prediction_drift(clf, ref, cur.drop(columns=["b"]))


def test_data_quality_matches_pandas():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"x": rng.normal(size=200), "const": 1, "cat": rng.choice(["p", "q"], 200)})
    df.loc[:19, "x"] = np.nan
    df = pd.concat([df, df.iloc[[50, 51]]], ignore_index=True)  # two copied rows
    report, table, _ = _athena_data_quality(df)
    assert report["rows"] == 202 and report["columns"] == 3
    assert report["duplicated_rows"] == df.duplicated().sum() >= 2  # the copies, and the rows missing x that share a cat
    assert report["constant_columns"] == 1
    assert report["missing_share"] == pytest.approx(df.isna().to_numpy().mean())
    row = table.set_index("column").loc["x"]
    assert row["missing_share"] == pytest.approx(df["x"].isna().mean())
    assert row["mean"] == pytest.approx(df["x"].mean()) and row["std"] == pytest.approx(df["x"].std(), rel=1e-6)
    assert table.set_index("column").loc["cat", "unique"] == 2

    ref = df.drop(columns=["cat"]).assign(extra=0)
    report, table, _ = _athena_data_quality(df, ref)
    assert report["new_columns"] == 1 and report["missing_columns"] == 1 and report["reference.rows"] == 202
    assert table.set_index("column").loc["x", "reference_mean"] == pytest.approx(ref["x"].mean())


def _drift_spec(ref_csv: Path, cur_csv: Path, on_fail: str) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "monitor", "nodes": [
        _n("ref", "csv_loader", path=str(ref_csv)), _n("cur", "csv_loader", path=str(cur_csv)),
        _n("drift", "evidently_drift"), _n("dq", "data_quality"),
        _n("gate", "quality_gate", rules="drifted_columns == 0", on_fail=on_fail),
    ], "edges": [_e("a", "cur", "drift", 0, 0), _e("b", "ref", "drift", 0, 1), _e("c", "cur", "dq", 0, 0),
                 _e("d", "ref", "dq", 0, 1), _e("g", "drift", "gate", 0, 0)]})


def test_a_run_serves_the_report_and_gates_on_drift(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    ref, cur = frames()
    ref.to_csv(tmp_path / "ref.csv", index=False)
    cur.to_csv(tmp_path / "cur.csv", index=False)
    run_id = str(uuid.uuid4())
    events: list[dict] = []
    status = run_spec(_drift_spec(tmp_path / "ref.csv", tmp_path / "cur.csv", "warn"), run_id, events.append,
                      lambda: False, tmp_path / "cache" / run_id)
    assert status == "completed"
    finish = {e["node_id"]: e for e in events if e["type"] == "node_finish"}
    assert finish["drift"]["documents"] == ["report.html"] and finish["dq"]["documents"] == ["report.html"]
    assert finish["gate"]["documents"] == []

    r = client.get(f"/api/runs/{run_id}/documents/drift/report.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "sandbox" in r.headers["content-security-policy"] and "<html" in r.text.lower()
    assert "attachment" in client.get(f"/api/runs/{run_id}/documents/drift/report.html?download=1").headers["content-disposition"]
    missing = client.get(f"/api/runs/{run_id}/documents/drift/other.html")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"
    assert client.get(f"/api/runs/{run_id}/documents/gate/report.html").status_code == 404

    run2 = str(uuid.uuid4())
    events = []
    assert run_spec(_drift_spec(tmp_path / "ref.csv", tmp_path / "cur.csv", "stop"), run2, events.append,
                    lambda: False, tmp_path / "cache" / run2) == "error"
    gate = next(e for e in events if e["type"] == "node_finish" and e["node_id"] == "gate")
    assert "drifted_columns == 0 (got 2)" in gate["error"]["message"]
