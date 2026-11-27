"""Clustering nodes and cluster evaluation."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog
from sklearn.datasets import make_blobs
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from athena.core.handler import ExecutionContext
from athena.nodes.cluster import (
    AgglomerativeHandler,
    ClusterEvalHandler,
    DbscanHandler,
    KMeansHandler,
)


def _ctx(config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="c1", node_type="t", config=config, inputs=inputs, run_id="r",
                            cache_dir=Path("."), logger=structlog.get_logger())


@pytest.fixture(scope="module")
def blobs():
    X, truth = make_blobs(n_samples=600, centers=4, cluster_std=0.8, random_state=3)
    df = pd.DataFrame(X, columns=["a", "b"])
    df["b"] *= 1000  # very different units: without standardising, "b" would dominate
    df["segment_name"] = "x"  # a text column is ignored when no columns are listed
    return df, truth


def test_kmeans_auto_k_recovers_the_clusters(blobs):
    df, truth = blobs
    res = KMeansHandler()(_ctx({}, [df]))
    out, model = res.outputs
    assert res.metrics["k"] == 4 and adjusted_rand_score(truth, out["cluster"]) > 0.95
    assert (model.predict(df[["a", "b"]]) == out["cluster"]).all()  # the model labels new rows in original units
    assert list(res.preview.columns[:3]) == ["cluster", "size", "share"]
    assert set(out.columns) == {"a", "b", "segment_name", "cluster"}


def test_kmeans_fixed_k_columns_and_errors(blobs):
    df, _ = blobs
    assert KMeansHandler()(_ctx({"n_clusters": 2, "cols": "a"}, [df])).metrics["k"] == 2
    with pytest.raises(ValueError, match="encode"):
        KMeansHandler()(_ctx({"cols": "a,segment_name"}, [df]))
    with pytest.raises(ValueError, match="missing values"):
        KMeansHandler()(_ctx({}, [df.assign(a=df["a"].where(df.index > 3))]))
    with pytest.raises(ValueError, match="not in the data"):
        KMeansHandler()(_ctx({"cols": "zzz"}, [df]))


def test_agglomerative_and_dbscan(blobs):
    df, truth = blobs
    agg = AgglomerativeHandler()(_ctx({"n_clusters": 4}, [df])).outputs[0]
    assert adjusted_rand_score(truth, agg["cluster"]) > 0.95
    noisy = pd.concat([df, pd.DataFrame({"a": [40.0, -40.0], "b": [40_000.0, -40_000.0], "segment_name": "x"})], ignore_index=True)
    res = DbscanHandler()(_ctx({"eps": 0.15}, [noisy]))  # the outliers stretch the standardised scale
    labels = res.outputs[0]["cluster"]
    assert res.metrics["k"] == 4 and labels.iloc[-2:].eq(-1).all()  # far-away points are noise
    assert 0 < res.metrics["noise_share"] < 0.1
    assert DbscanHandler()(_ctx({"eps": 0.0001}, [df])).metrics["k"] == 0  # everything noise: warns, doesn't fail
    with pytest.raises(ValueError, match="quadratic"):
        AgglomerativeHandler()(_ctx({}, [pd.DataFrame({"a": np.zeros(20_001)})]))


def test_cluster_eval_matches_sklearn(blobs):
    df, _ = blobs
    labelled = KMeansHandler()(_ctx({"n_clusters": 4}, [df])).outputs[0]
    res = ClusterEvalHandler()(_ctx({}, [labelled]))
    report, profile = res.outputs
    X = StandardScaler().fit_transform(labelled[["a", "b"]])
    assert report["silhouette"] == pytest.approx(silhouette_score(X, labelled["cluster"]))
    assert report["davies_bouldin"] == pytest.approx(davies_bouldin_score(X, labelled["cluster"]))
    assert profile["size"].sum() == len(df) and profile["share"].sum() == pytest.approx(1)
    assert res.preview.kind == "plot"
    with pytest.raises(ValueError, match="connect a clustering node"):
        ClusterEvalHandler()(_ctx({}, [df]))


def test_cluster_eval_excludes_noise(blobs):
    df, _ = blobs
    labels = KMeansHandler()(_ctx({"n_clusters": 4}, [df])).outputs[0]["cluster"].to_numpy().copy()
    labels[:30] = -1
    report = ClusterEvalHandler()(_ctx({}, [df.assign(cluster=labels)])).outputs[0]
    assert report["noise_share"] == pytest.approx(30 / 600) and report["clusters"] == 4
