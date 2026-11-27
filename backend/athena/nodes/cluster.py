"""Clustering: K-Means (with automatic k), hierarchical, DBSCAN, and cluster evaluation.

Clustering nodes add a ``cluster`` column to the table (DBSCAN marks noise as -1). Features are the numeric
columns (or the ones listed), standardised by default so no column dominates by its units. The ``_athena_*``
helpers are self-contained and copied verbatim into exported scripts.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe
from athena.utils.plotting import SERIES, fig_to_plot_preview, style_axes

# ---- helpers copied into exports ------------------------------------------------------------------------

def _athena_cluster_matrix(df, cols="", scale=True, label_col="cluster"):
    """(feature matrix, column names): the listed columns, else every numeric column except the label."""
    import numpy as np
    import pandas as pd
    names = [c.strip() for c in str(cols).split(",") if c.strip()]
    if names:
        missing = [c for c in names if c not in df.columns]
        if missing:
            raise ValueError(f"Columns not in the data: {missing}")
    else:
        names = [c for c in df.columns if c != label_col and pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    text = [c for c in names if not pd.api.types.is_numeric_dtype(df[c])]
    if text:
        raise ValueError(f"Clustering needs numeric columns; encode {text[:5]} first")
    if not names:
        raise ValueError("No numeric columns to cluster on")
    X = df[names].to_numpy(dtype=float)
    if np.isnan(X).any():
        raise ValueError("Features contain missing values: impute them first")
    if scale:
        from sklearn.preprocessing import StandardScaler
        X = StandardScaler().fit_transform(X)
    return X, names


def _athena_silhouette(X, labels):
    """Silhouette over clustered points (noise excluded), on a fixed 5,000-row sample for large data."""
    import numpy as np
    from sklearn.metrics import silhouette_score
    keep = np.asarray(labels) != -1
    if len(set(np.asarray(labels)[keep])) < 2:
        return float("nan")
    n = int(keep.sum())
    return float(silhouette_score(X[keep], np.asarray(labels)[keep], sample_size=5000 if n > 5000 else None, random_state=0))


def _athena_auto_k(X, k_max=10, random_state=42):
    """The k in 2..k_max with the best silhouette. Returns (k, {k: silhouette})."""
    from sklearn.cluster import KMeans
    scores = {}
    for k in range(2, max(2, min(int(k_max), len(X) - 1)) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit_predict(X)
        scores[k] = _athena_silhouette(X, labels)
    return max(scores, key=lambda k: scores[k]), scores


def _athena_cluster_profile(df, labels, names):
    """One row per cluster: size, share, and the mean of each feature (in original units)."""
    d = df[names].assign(cluster=labels)
    prof = d.groupby("cluster").mean(numeric_only=True)
    prof.insert(0, "share", d["cluster"].value_counts(normalize=True).reindex(prof.index))
    prof.insert(0, "size", d["cluster"].value_counts().reindex(prof.index))
    return prof.reset_index()


# ---- nodes ---------------------------------------------------------------------------------------------

COMMON = {
    "cols": ui("Columns", help="Comma-separated features. Empty = every numeric column."),
    "scale": ui("Standardise features", help="Recommended: otherwise columns with large units dominate the distances."),
}


def _finish(ctx: ExecutionContext, df: pd.DataFrame, labels: Any, X: np.ndarray, names: list[str],
            outputs_extra: list[Any], metrics: dict[str, float]) -> HandlerResult:
    out = df.copy()
    out["cluster"] = labels
    sil = _athena_silhouette(X, labels)
    if np.isfinite(sil):
        metrics["silhouette"] = sil
    profile = _athena_cluster_profile(df, labels, names)
    for row in profile.to_dict("records"):
        ctx.logger.info(f"Cluster {row['cluster']}", size=int(row["size"]), share=f"{row['share']:.1%}")
    return HandlerResult(outputs=[out, *outputs_extra], preview=preview_dataframe(profile.round(4)), metrics=metrics)


@node(
    "kmeans", label="K-Means", category="cluster",
    description="Group rows into k clusters around centroids; k = 0 picks k by silhouette",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset"), Port("model", "model")],
    fields={"n_clusters": ui("Clusters (k)", help="0 = try 2 to Max k and keep the best silhouette."),
            "k_max": ui("Max k"), **COMMON, "random_state": ui("Random state")},
    code=EXPORT["kmeans"],
)
class KMeansHandler:
    class Config(BaseModel):
        n_clusters: int = Field(0, ge=0, le=100)
        k_max: int = Field(10, ge=2, le=50)
        cols: str = ""
        scale: bool = True
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.cluster import KMeans
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        cfg = self.Config(**ctx.config)
        df = ctx.inputs[0]
        X, names = _athena_cluster_matrix(df, cfg.cols, cfg.scale)
        k = cfg.n_clusters
        if k == 0:
            k, scores = _athena_auto_k(X, cfg.k_max, cfg.random_state)
            ctx.logger.info("Silhouette by k", **{f"k{key}": round(v, 4) for key, v in scores.items()})
            ctx.logger.info(f"Chose k = {k}")
        km = KMeans(n_clusters=k, n_init=10, random_state=cfg.random_state)
        model = (make_pipeline(StandardScaler(), km) if cfg.scale else km).fit(df[names])  # predicts on new rows in original units
        return _finish(ctx, df, km.labels_, X, names, [model], {"k": float(k), "inertia": float(km.inertia_)})


@node(
    "agglomerative", label="Hierarchical Clustering", category="cluster",
    description="Agglomerative clustering: merge the closest groups until k remain",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
    fields={"n_clusters": ui("Clusters (k)"), "linkage": ui("Linkage", help="ward makes compact, similar-sized clusters; "
                                                                               "single can follow long, thin shapes."), **COMMON},
    code=EXPORT["agglomerative"],
)
class AgglomerativeHandler:
    class Config(BaseModel):
        n_clusters: int = Field(3, ge=2, le=100)
        linkage: Literal["ward", "average", "complete", "single"] = "ward"
        cols: str = ""
        scale: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.cluster import AgglomerativeClustering
        cfg = self.Config(**ctx.config)
        df = ctx.inputs[0]
        if len(df) > 20_000:
            raise ValueError(f"Hierarchical clustering needs memory quadratic in rows ({len(df):,}); sample first or use K-Means")
        X, names = _athena_cluster_matrix(df, cfg.cols, cfg.scale)
        labels = AgglomerativeClustering(n_clusters=cfg.n_clusters, linkage=cfg.linkage).fit_predict(X)
        return _finish(ctx, df, labels, X, names, [], {"k": float(cfg.n_clusters)})


@node(
    "dbscan", label="DBSCAN", category="cluster",
    description="Density-based clusters of any shape; points in sparse regions become noise (-1)",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
    fields={"eps": ui("Neighbourhood radius (eps)", help="In standardised units when Standardise is on. Larger = fewer, bigger clusters."),
            "min_samples": ui("Min samples"), **COMMON},
    code=EXPORT["dbscan"],
)
class DbscanHandler:
    class Config(BaseModel):
        eps: float = Field(0.5, gt=0)
        min_samples: int = Field(5, ge=1)
        cols: str = ""
        scale: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.cluster import DBSCAN
        cfg = self.Config(**ctx.config)
        df = ctx.inputs[0]
        X, names = _athena_cluster_matrix(df, cfg.cols, cfg.scale)
        labels = DBSCAN(eps=cfg.eps, min_samples=cfg.min_samples).fit_predict(X)
        k, noise = len(set(labels) - {-1}), float(np.mean(labels == -1))
        if k == 0:
            ctx.logger.warning("Everything is noise: increase eps or lower min samples")
        elif k == 1 and noise < 0.01:
            ctx.logger.warning("One cluster holds everything: decrease eps")
        elif noise > 0.3:
            ctx.logger.warning(f"{noise:.0%} of rows are noise: increase eps if that's too many")
        return _finish(ctx, df, labels, X, names, [], {"k": float(k), "noise_share": noise})


@node(
    "cluster_eval", label="Cluster Evaluation", category="cluster",
    description="Silhouette, Davies-Bouldin and Calinski-Harabasz scores, a 2-D map of the clusters and a per-cluster profile",
    inputs=[Port("dataset", "dataset")], outputs=[Port("report", "report"), Port("profile", "dataset")],
    fields={"label_col": ui("Cluster column"), **COMMON},
    code=EXPORT["cluster_eval"],
)
class ClusterEvalHandler:
    class Config(BaseModel):
        label_col: str = "cluster"
        cols: str = ""
        scale: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df = ctx.inputs[0]
        if cfg.label_col not in df.columns:
            raise ValueError(f"No {cfg.label_col!r} column: connect a clustering node first, or set Cluster column")
        X, names = _athena_cluster_matrix(df, cfg.cols, cfg.scale, cfg.label_col)
        labels = df[cfg.label_col].to_numpy()
        report, profile = _athena_cluster_report(X, labels), _athena_cluster_profile(df, labels, names)
        ctx.logger.info("Cluster quality", **{k: round(v, 4) for k, v in report.items()})
        return HandlerResult(outputs=[report, profile], preview=fig_to_plot_preview(_cluster_map(X, labels, report)), metrics=report)


def _athena_cluster_report(X, labels):
    """Silhouette (higher is better, -1..1), Davies-Bouldin (lower is better), Calinski-Harabasz (higher is better)."""
    import numpy as np
    from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score
    labels = np.asarray(labels)
    keep = labels != -1
    k = len(set(labels[keep]))
    report = {"clusters": float(k), "noise_share": float(np.mean(~keep))}
    if k >= 2:
        report["silhouette"] = _athena_silhouette(X, labels)
        report["davies_bouldin"] = float(davies_bouldin_score(X[keep], labels[keep]))
        report["calinski_harabasz"] = float(calinski_harabasz_score(X[keep], labels[keep]))
    return report


def _cluster_map(X: np.ndarray, labels: np.ndarray, report: dict[str, float]) -> Any:
    """Rows projected onto their first two principal components, coloured by cluster (largest clusters first)."""
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA
    xy = PCA(n_components=2, random_state=0).fit_transform(X) if X.shape[1] > 1 else np.column_stack([X[:, 0], np.zeros(len(X))])
    sizes = pd.Series(labels[labels != -1]).value_counts()
    # colour follows the cluster id, not its size rank; past 8 clusters the smallest fold into "Other"
    shown = sorted(sizes.index[: len(SERIES) - 1] if len(sizes) > len(SERIES) else sizes.index)
    fig, ax = plt.subplots(figsize=(7, 5))
    rng = np.random.default_rng(0)
    idx = rng.choice(len(X), size=min(len(X), 4000), replace=False)  # keep the plot readable on large data
    xs, ls = xy[idx], labels[idx]
    other = ~np.isin(ls, shown)
    if other.any():
        name = "Noise" if set(ls[other]) == {-1} else "Other / noise"
        ax.scatter(xs[other, 0], xs[other, 1], s=10, color="#bbbbbb", label=name, linewidths=0)
    for c, color in zip(shown, SERIES):
        sel = ls == c
        ax.scatter(xs[sel, 0], xs[sel, 1], s=14, color=color, label=f"Cluster {c} ({sizes[c]:,})", edgecolors="white", linewidths=0.4)
    sil = f" · silhouette {report['silhouette']:.3f}" if "silhouette" in report else ""
    ax.set_title(f"{int(report['clusters'])} clusters{sil}", fontsize=11, loc="left")
    ax.set_xlabel("Principal component 1"); ax.set_ylabel("Principal component 2")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8.5, frameon=False)
    style_axes(ax)
    fig.tight_layout()
    return fig
