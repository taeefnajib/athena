"""Cross-run caching, partial runs (run from selected node), eviction and dataset snapshots."""
import io
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from athena.core.cache import (
    ArtifactCache,
    compute_cache_key,
    read_index,
    source_fingerprint,
)
from athena.main import clear_cache
from athena.nodes.snapshot import _athena_snapshot
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec

BACKEND = Path(__file__).parents[1]


def _spec(csv: Path, nodes_extra: list[dict] | None = None, edges_extra: list[dict] | None = None, **cfg) -> PipelineSpec:
    nodes = [
        {"id": "csv", "type": "csv_loader", "position": {"x": 0, "y": 0}, "config": {"path": str(csv)}},
        {"id": "imp", "type": "imputer", "position": {"x": 0, "y": 0}, "config": {"strategy": cfg.get("strategy", "mean")}},
        {"id": "sc", "type": "scaler", "position": {"x": 0, "y": 0}, "config": {"method": cfg.get("method", "StandardScaler")}},
        {"id": "info", "type": "df_info", "position": {"x": 0, "y": 0}, "config": {}},  # a side branch off the loader
    ]
    edges = [{"id": "a", "source": "csv", "target": "imp"}, {"id": "b", "source": "imp", "target": "sc"},
             {"id": "c", "source": "csv", "target": "info"}]
    return PipelineSpec.model_validate({"name": "cache", "nodes": nodes + (nodes_extra or []), "edges": edges + (edges_extra or [])})


def _run(spec: PipelineSpec, root: Path, run: str, start_from: list[str] | None = None) -> dict[str, dict]:
    """Run and return {node_id: node_finish event}; asserts the run completed."""
    events: list[dict] = []
    status = run_spec(spec, run, events.append, lambda: False, root / run, start_from=start_from)
    assert status == "completed", [e for e in events if e.get("status") == "error"]
    return {e["node_id"]: e for e in events if e["type"] == "node_finish"}


@pytest.fixture
def csv(tmp_path: Path) -> Path:
    p = tmp_path / "data.csv"
    p.write_bytes((BACKEND / "data.csv").read_bytes())
    return p


def test_second_run_reuses_every_node(tmp_path: Path, csv: Path):
    first = _run(_spec(csv), tmp_path, "r1")
    second = _run(_spec(csv), tmp_path, "r2")
    assert not any(e["cached"] for e in first.values())
    assert all(e["cached"] for e in second.values())
    assert second["sc"]["preview"] == first["sc"]["preview"]
    assert read_index(tmp_path / "r2") == read_index(tmp_path / "r1")  # same store entries


def test_editing_a_node_recomputes_it_and_its_descendants_only(tmp_path: Path, csv: Path):
    _run(_spec(csv), tmp_path, "r1")
    after = _run(_spec(csv, method="MinMaxScaler"), tmp_path, "r2")
    assert after["csv"]["cached"] and after["imp"]["cached"] and after["info"]["cached"]
    assert not after["sc"]["cached"]
    mid = _run(_spec(csv, strategy="median", method="MinMaxScaler"), tmp_path, "r3")
    assert mid["csv"]["cached"] and not mid["imp"]["cached"] and not mid["sc"]["cached"]


def test_changing_the_input_file_invalidates_downstream(tmp_path: Path, csv: Path):
    _run(_spec(csv), tmp_path, "r1")
    df = pd.read_csv(csv)
    df.iloc[0, 0] = 999.0
    time.sleep(0.01)
    df.to_csv(csv, index=False)
    after = _run(_spec(csv), tmp_path, "r2")
    assert not any(e["cached"] for e in after.values())  # the file changed: nothing downstream is stale


def test_side_effect_nodes_always_run_but_keep_downstream_cached(tmp_path: Path, csv: Path):
    snaps = tmp_path / "snaps"
    extra = [{"id": "exp", "type": "dataset_snapshot", "position": {"x": 0, "y": 0}, "config": {"folder": str(snaps)}},
             {"id": "after", "type": "df_info", "position": {"x": 0, "y": 0}, "config": {}}]
    edges = [{"id": "d", "source": "sc", "target": "exp"}, {"id": "e", "source": "exp", "target": "after"}]
    _run(_spec(csv, extra, edges), tmp_path, "r1")
    (written,) = list(snaps.glob("*.parquet"))
    written.unlink()
    again = _run(_spec(csv, extra, edges), tmp_path, "r2")
    assert not again["exp"]["cached"] and written.exists()  # the snapshot ran again and rewrote its file
    assert again["after"]["cached"]  # its output didn't change, so downstream stays cached


def test_live_nodes_invalidate_downstream_only_when_their_output_changes(tmp_path: Path, csv: Path):
    code = "df['noise'] = np.random.default_rng().normal(size=len(df))\nreturn df"
    fixed = "df['noise'] = 1.0\nreturn df"
    def spec(src: str) -> PipelineSpec:
        extra = [{"id": "cc", "type": "custom_code", "position": {"x": 0, "y": 0}, "config": {"code": src}},
                 {"id": "down", "type": "df_info", "position": {"x": 0, "y": 0}, "config": {}}]
        return _spec(csv, extra, [{"id": "d", "source": "csv", "target": "cc"}, {"id": "e", "source": "cc", "target": "down"}])
    _run(spec(code), tmp_path, "r1")
    random_again = _run(spec(code), tmp_path, "r2")
    assert not random_again["cc"]["cached"] and not random_again["down"]["cached"]  # new random output
    _run(spec(fixed), tmp_path, "r3")
    same = _run(spec(fixed), tmp_path, "r4")
    assert not same["cc"]["cached"] and same["down"]["cached"]  # ran again, same output: downstream reused


def test_node_cache_off_always_runs(tmp_path: Path, csv: Path):
    spec = _spec(csv)
    spec.nodes[1].cache = False
    _run(spec, tmp_path, "r1")
    again = _run(spec, tmp_path, "r2")
    assert not again["imp"]["cached"] and again["csv"]["cached"]
    assert again["sc"]["cached"]  # the imputer's output is unchanged, so the scaler is reused


def test_run_from_selected_node(tmp_path: Path, csv: Path):
    _run(_spec(csv), tmp_path, "r1")
    partial = _run(_spec(csv), tmp_path, "r2", start_from=["imp"])
    assert set(partial) == {"csv", "imp", "sc"}  # the unrelated branch (info) is skipped
    assert partial["csv"]["cached"]  # ancestors come from the cache
    assert not partial["imp"]["cached"] and not partial["sc"]["cached"]  # the selection and below re-run


def test_run_from_selected_computes_uncached_ancestors(tmp_path: Path, csv: Path):
    events = _run(_spec(csv), tmp_path, "r1", start_from=["sc"])
    assert set(events) == {"csv", "imp", "sc"} and not any(e["cached"] for e in events.values())
    assert _run(_spec(csv), tmp_path, "r2", start_from=["nope"]) == {}  # unknown ids select nothing


def test_eviction_keeps_the_current_run(tmp_path: Path):
    store = ArtifactCache(tmp_path / "store")
    for i in range(5):
        store.set(f"k{i}", np.zeros(50_000))
        os.utime(store.dir / f"k{i}.pkl", (1000 + i, 1000 + i))
    store.get("k0")  # reading refreshes recency
    store.evict(max_bytes=2 * 410_000, keep={"k1"})
    left = sorted(p.stem for p in store.dir.glob("*.pkl"))
    assert "k0" in left and "k1" in left and "k2" not in left


def test_fingerprints_follow_files_and_folders(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("x\n1\n")
    folder = tmp_path / "lake"
    folder.mkdir()
    (folder / "p1.parquet").write_bytes(b"1")
    before = (source_fingerprint({"path": str(f)}), source_fingerprint({"path": str(folder)}))
    time.sleep(0.01)
    f.write_text("x\n2\n")
    (folder / "p2.parquet").write_bytes(b"2")
    after = (source_fingerprint({"path": str(f)}), source_fingerprint({"path": str(folder)}))
    assert before[0] != after[0] and before[1] != after[1]
    assert source_fingerprint({"sql": "SELECT 1", "path": "s3://bucket/x"}) == ""
    assert compute_cache_key("t", {}, []) != compute_cache_key("t", {}, [], salt="run")


def test_downloads_work_for_cached_runs(tmp_path: Path, csv: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from athena.config import settings
    from athena.main import app
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_a, run_b = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    _run(_spec(csv), tmp_path / "cache", run_a)
    _run(_spec(csv), tmp_path / "cache", run_b)
    res = TestClient(app).get(f"/api/runs/{run_b}/artifacts/imp/0")
    assert res.status_code == 200 and len(pd.read_csv(io.BytesIO(res.content))) == 300


def test_shutdown_cleanup(tmp_path: Path):
    for keep in (True, False):
        root = tmp_path / str(keep)
        (root / "store").mkdir(parents=True)
        (root / "store" / "k.pkl").write_bytes(b"x")
        (root / "run1").mkdir()
        clear_cache(root, keep_store=keep)
        assert not (root / "run1").exists() and (root / "store" / "k.pkl").exists() == keep


def test_snapshot_is_content_addressed(tmp_path: Path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    p1, h1 = _athena_snapshot(df, tmp_path, "train")
    mtime = os.stat(p1).st_mtime_ns
    p2, h2 = _athena_snapshot(df.copy(), tmp_path, "train")
    assert (p1, h1) == (p2, h2) and os.stat(p1).st_mtime_ns == mtime  # same data: same file, written once
    assert Path(p1).name == f"train-{h1}.parquet" and pd.read_parquet(p1).equals(df)
    _, h3 = _athena_snapshot(df.assign(a=[1, 2, 4]), tmp_path, "train")
    _, h4 = _athena_snapshot(df.astype({"a": float}), tmp_path, "train")
    assert len({h1, h3, h4}) == 3  # a changed value or type gives a new snapshot
    _, h5 = _athena_snapshot(pd.DataFrame({"tags": [["a"], ["b"]]}), tmp_path)
    assert len(h5) == 16
