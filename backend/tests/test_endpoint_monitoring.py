"""Local endpoints expose Prometheus metrics and log their requests; Endpoint Requests turns the log into a table
that drift nodes compare with the training data."""
import json
import re
import uuid
from pathlib import Path

import pandas as pd
import pytest

from athena.config import settings
from athena.nodes.traffic import _athena_endpoint_requests
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec
from athena.serving import endpoints
from tests.test_serving import _bundle, _e, _messy_csv, _messy_spec, _n, _run, client


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    yield tmp_path
    endpoints.stop_all()


def _metric(text: str, name: str) -> float:
    m = re.search(rf"^{re.escape(name)} (\S+)$", text, re.MULTILINE)
    assert m, f"{name} not in metrics:\n{text}"
    return float(m.group(1))


def test_endpoint_metrics_request_log_and_drift_on_live_traffic(data_dir: Path):
    pytest.importorskip("evidently")
    csv = _messy_csv(data_dir)
    spec = _messy_spec(csv)
    b = _bundle(spec, _run(spec, data_dir), "rf", "messy")
    slug = b["slug"]
    listed = next(x for x in client.get("/api/serving/bundles").json()["bundles"] if x["slug"] == slug)
    assert listed["monitoring"]["logs_requests"] and listed["monitoring"]["requests_logged"] == 0
    assert client.get(f"/api/serving/endpoints/{slug}/metrics").status_code == 409  # not running yet

    started = client.post(f"/api/serving/endpoints/{slug}").json()
    assert started["metrics_url"].endswith("/metrics")
    raw = pd.read_csv(csv).drop(columns=["target"])
    as_rows = lambda df: json.loads(df.to_json(orient="records"))
    normal = as_rows(raw.iloc[:60])
    shifted = as_rows(raw.iloc[60:120].assign(income=lambda d: d["income"] + 40))
    for rows in (normal, shifted):
        assert client.post(f"/api/serving/endpoints/{slug}/predict", json={"rows": rows}).json()["status"] == 200
    assert client.post(f"/api/serving/endpoints/{slug}/predict", json={"rows": [{"age": 1}]}).json()["status"] == 422

    text = client.get(f"/api/serving/endpoints/{slug}/metrics").text
    assert _metric(text, 'athena_requests_total{status="200"}') == 2 and _metric(text, 'athena_requests_total{status="422"}') == 1
    assert _metric(text, "athena_rows_predicted_total") == 120 and _metric(text, "athena_request_duration_seconds_count") == 3
    assert _metric(text, 'athena_request_duration_seconds_bucket{le="+Inf"}') == 3
    by_class = [float(v) for v in re.findall(r'^athena_predictions_total\{class="[^"]+"\} (\S+)$', text, re.MULTILINE)]
    assert sum(by_class) == 120 and 'athena_model_info{name="messy"' in text
    listed = next(x for x in client.get("/api/serving/bundles").json()["bundles"] if x["slug"] == slug)
    assert listed["monitoring"]["requests_logged"] == 120  # the rejected request isn't logged

    monitor = PipelineSpec.model_validate({"name": "monitor", "nodes": [
        _n("train", "csv_loader", path=str(csv)), _n("live", "endpoint_requests", model="messy"),
        _n("recent", "endpoint_requests", model="Messy", last_n=60, include_prediction=False),
        _n("drift", "evidently_drift", columns="age, income, plan"), _n("drift_recent", "evidently_drift", columns="age, income, plan"),
    ], "edges": [_e("a", "live", "drift", 0, 0), _e("b", "train", "drift", 0, 1),
                 _e("c", "recent", "drift_recent", 0, 0), _e("d", "train", "drift_recent", 0, 1)]})
    run_id = str(uuid.uuid4())
    events: list[dict] = []
    assert run_spec(monitor, run_id, events.append, lambda: False, data_dir / "cache" / run_id) == "completed", events[-3:]
    from athena.core.artifacts import load_output
    live = load_output(run_id, "live", 0)
    assert list(live.columns) == ["age", "income", "plan", "signup", "prediction", "timestamp"] and len(live) == 120
    assert str(live["timestamp"].dtype).startswith("datetime64") and live["income"].isna().sum() == raw.iloc[:120]["income"].isna().sum()
    recent = load_output(run_id, "recent", 0)
    assert len(recent) == 60 and "prediction" not in recent.columns
    pd.testing.assert_series_equal(recent["income"], (raw["income"].iloc[60:120] + 40).reset_index(drop=True), check_names=False)
    drifted = load_output(run_id, "drift_recent", 1).set_index("column")["drifted"]
    assert drifted["income"] and not drifted["age"]  # only the shifted feature


def test_reading_the_request_log(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    with pytest.raises(ValueError, match="No requests logged"):
        _athena_endpoint_requests(logs)
    (logs / "requests.1.jsonl").write_text('{"x": 1, "prediction": 0, "timestamp": "2026-01-01T00:00:00.000+00:00"}\n', encoding="utf-8")
    (logs / "requests.jsonl").write_text('{"x": 2, "prediction": 1, "timestamp": "2026-01-02T00:00:00.000+00:00"}\n{"x": 3, "predi',
                                         encoding="utf-8")  # the last line is still being written
    df = _athena_endpoint_requests(logs)
    assert df["x"].tolist() == [1, 2] and df["timestamp"].dt.day.tolist() == [1, 2]  # rotated file first
    assert _athena_endpoint_requests(logs, last_n=1)["x"].tolist() == [2]


def test_unknown_model_lists_the_deployed_ones(data_dir: Path):
    from athena.nodes.traffic import request_folder
    with pytest.raises(ValueError, match="Choose the deployed model"):
        request_folder(" ")
    with pytest.raises(ValueError, match="Deploy one first"):
        request_folder("nope")
