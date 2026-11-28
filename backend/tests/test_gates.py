"""Quality gates, fairness checks, and the evidence (metrics, gates, model card) that goes into a deployed bundle."""
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from athena.config import settings
from athena.core.handler import ExecutionContext
from athena.main import app
from athena.nodes.gates import (
    FairnessCheckHandler,
    QualityGateHandler,
    _athena_check_rules,
    _athena_fairness,
)
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec

client = TestClient(app)


def _ctx(config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="g", node_type="t", config=config, inputs=inputs, run_id="r", cache_dir=Path("."), logger=structlog.get_logger())


def test_rules_are_checked_and_explained():
    res = _athena_check_rules([{"f1": 0.91, "roc_auc": 0.8}, {"drifted_columns": 0}, None],
                              "f1 >= 0.9   # main target\n\nroc_auc > 0.85\ndrifted_columns == 0")
    assert [(m, ok) for _, m, _, ok in res] == [("f1", True), ("roc_auc", False), ("drifted_columns", True)]
    with pytest.raises(ValueError, match="write it like"):
        _athena_check_rules([{"f1": 1}], "f1 is great")
    with pytest.raises(ValueError, match="Available: f1"):
        _athena_check_rules([{"f1": 1}], "accuracy >= 0.5")
    with pytest.raises(ValueError, match="at least one rule"):
        _athena_check_rules([{"f1": 1}], "# nothing")


def test_gate_stops_or_warns_and_passes_the_model_through():
    model = object()
    ok = QualityGateHandler()(_ctx({"rules": "f1 >= 0.9"}, [{"f1": 0.95}, None, None, model]))
    assert ok.outputs[0] is model and ok.outputs[1] == {"passed": 1.0, "rules_passed": 1.0, "rules_total": 1.0}
    with pytest.raises(ValueError, match=r"Quality gate failed: f1 >= 0.9 \(got 0.8\)"):
        QualityGateHandler()(_ctx({"rules": "f1 >= 0.9"}, [{"f1": 0.8}, None, None, model]))
    warned = QualityGateHandler()(_ctx({"rules": "f1 >= 0.9", "on_fail": "warn"}, [{"f1": 0.8}, None, None, model]))
    assert warned.outputs[0] is model and warned.outputs[1]["passed"] == 0.0 and "FAILED" in warned.preview.text


def _n(nid, ntype, **config):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config}


def _e(eid, s, t, sp=0, tp=0):
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


def groups_csv(tmp: Path) -> Path:
    """A binary task with a 'region' group the labels (and so the model) treat differently."""
    rng = np.random.default_rng(1)
    n = 600
    df = pd.DataFrame({"x1": rng.normal(size=n), "x2": rng.normal(size=n), "region": rng.integers(0, 3, n)})
    df["target"] = ((df["x1"] + 0.8 * (df["region"] == 2) + rng.normal(0, 0.5, n)) > 0.4).astype(int)
    path = tmp / "groups.csv"
    df.to_csv(path, index=False)
    return path


def _gated_spec(csv: Path, rules: str, saver_path: Path) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "gated", "nodes": [
        _n("csv", "csv_loader", path=str(csv)), _n("tt", "train_test", stratify=True), _n("lr", "log_reg"),
        _n("m", "metrics"), _n("fair", "fairness_check", sensitive_col="region"),
        _n("gate", "quality_gate", rules=rules), _n("save", "model_saver", path=str(saver_path)),
    ], "edges": [_e("a", "csv", "tt"), _e("b", "tt", "lr", 0, 0), _e("c", "tt", "lr", 1, 1),
                 _e("d", "lr", "m", 0, 0), _e("e", "tt", "m", 2, 1), _e("f", "tt", "m", 3, 2),
                 _e("g", "lr", "fair", 0, 0), _e("h", "tt", "fair", 2, 1), _e("i", "tt", "fair", 3, 2),
                 _e("j", "m", "gate", 0, 0), _e("k", "fair", "gate", 0, 1), _e("l", "lr", "gate", 0, 3),
                 _e("s", "gate", "save", 0, 0)]})


def _run(spec: PipelineSpec, cache: Path) -> tuple[str, list[dict]]:
    events: list[dict] = []
    status = run_spec(spec, str(uuid.uuid4()), events.append, lambda: False, cache)
    return status, events


def test_a_failing_gate_stops_everything_after_it(tmp_path: Path):
    csv = groups_csv(tmp_path)
    status, events = _run(_gated_spec(csv, "f1 >= 0.999", tmp_path / "blocked.joblib"), tmp_path / "c1")
    finished = {e["node_id"]: e["status"] for e in events if e["type"] == "node_finish"}
    assert status == "error" and finished["gate"] == "error" and "save" not in finished
    assert not (tmp_path / "blocked.joblib").exists()  # the failing model never reached Model Saver
    status, _ = _run(_gated_spec(csv, "f1 >= 0.5\ndemographic_parity_difference <= 0.9", tmp_path / "ok.joblib"), tmp_path / "c2")
    assert status == "completed" and (tmp_path / "ok.joblib").exists()


def test_fairness_numbers_match_a_hand_calculation(tmp_path: Path):
    df = pd.read_csv(groups_csv(tmp_path))
    X, y = df[["x1", "x2", "region"]], df["target"]
    model = LogisticRegression().fit(X, y)
    report, groups = _athena_fairness(model, X, y, "region")
    pred = model.predict(X) == 1
    sel = [pred[(X["region"] == g).to_numpy()].mean() for g in (0, 1, 2)]
    assert [g["group"] for g in groups] == ["0", "1", "2"]
    assert report["demographic_parity_difference"] == pytest.approx(max(sel) - min(sel))
    assert report["disparate_impact_ratio"] == pytest.approx(min(sel) / max(sel))
    assert report["demographic_parity_difference"] > 0.1  # the built-in bias shows up
    res = FairnessCheckHandler()(_ctx({"sensitive_col": "region"}, [model, X, y]))
    assert res.preview.kind == "plot" and res.metrics["groups"] == 3
    with pytest.raises(ValueError, match="distinct values"):
        _athena_fairness(model, X, y, "x1")
    with pytest.raises(ValueError, match="isn't in the test features"):
        _athena_fairness(model, X, y, "gender")
    with pytest.raises(ValueError, match="Choose the sensitive column"):
        FairnessCheckHandler()(_ctx({}, [model, X, y]))


def test_bundles_carry_the_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    csv = groups_csv(tmp_path)
    spec = _gated_spec(csv, "f1 >= 0.5", tmp_path / "m.joblib")
    run_id = str(uuid.uuid4())
    assert run_spec(spec, run_id, lambda e: None, lambda: False, tmp_path / "cache" / run_id) == "completed"
    for node in ("lr", "gate"):  # deploying the model, or the gate's output, finds the same evidence
        b = client.post("/api/serving/bundles", json={"name": f"m-{node}", "spec": spec.model_dump(), "run_id": run_id, "node_id": node}).json()
        assert [e["node"] for e in b["evaluation"]] == ["Metrics Node", "Fairness Check"]
        assert b["quality_gates"] == [{"node": "Quality Gate", "id": "gate", "rules": "f1 >= 0.5", "on_fail": "stop", "passed": True}]
        card = (Path(b["path"]) / "MODEL_CARD.md").read_text(encoding="utf-8")
        assert "| f1 |" in card and "demographic_parity_difference" in card and "passed" in card and "_to complete" in card

    blocked = _gated_spec(csv, "f1 >= 0.999", tmp_path / "x.joblib")
    run2 = str(uuid.uuid4())
    run_spec(blocked, run2, lambda e: None, lambda: False, tmp_path / "cache" / run2)
    b = client.post("/api/serving/bundles", json={"name": "blocked", "spec": blocked.model_dump(), "run_id": run2, "node_id": "lr"}).json()
    assert b["quality_gates"][0]["passed"] is None  # the gate stopped the run: no pass to claim
    assert "did not pass in this run" in (Path(b["path"]) / "MODEL_CARD.md").read_text(encoding="utf-8")


def test_worker_logs_non_ascii_characters():
    """A node logging '✓' (or a column named 'São Paulo') must not crash the worker on a Windows code page."""
    import subprocess
    import sys
    code = ("import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='cp1252');"
            "from athena.utils.tracing import utf8_output; utf8_output(); print('✓ São Paulo ✗')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    assert "São Paulo" in out.stdout.decode("utf-8")
