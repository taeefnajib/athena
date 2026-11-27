"""Dataset profiling: schema, per-column statistics, data-quality insights and target association.

Pure functions of a DataFrame returning JSON-safe dicts (served by GET /api/runs/{run}/profile/...). Large
frames are profiled on a random sample, and the result says so.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

SAMPLE_ROWS = 100_000
ASSOCIATION_ROWS = 20_000
HIST_BINS = 20
TOP_VALUES = 10


def _num(x: Any) -> float | int | None:
    """JSON-safe number (NaN/inf -> None)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return int(f) if float(f).is_integer() and abs(f) < 2**53 and isinstance(x, (int, np.integer)) else round(f, 6)


def _label(v: Any) -> str:
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "…"


def column_kind(s: pd.Series) -> str:
    """numeric | binary | categorical | text | datetime | empty"""
    nonnull = s.dropna()
    if nonnull.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(s):
        return "binary"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        return "binary" if nonnull.nunique() == 2 and set(nonnull.unique()) <= {0, 1} else "numeric"
    sample = nonnull.astype(str).head(200)
    if len(sample) >= 5 and sample.str.len().between(6, 40).all():
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        if parsed.notna().mean() > 0.9:
            return "datetime"
    if nonnull.nunique() == 2:
        return "binary"
    if nonnull.astype(str).str.len().mean() > 30 and nonnull.nunique() > 0.5 * len(nonnull):
        return "text"
    return "categorical"


def column_profile(s: pd.Series) -> dict[str, Any]:
    n = len(s)
    nonnull = s.dropna()
    unique = int(nonnull.nunique())
    kind = column_kind(s)
    out: dict[str, Any] = {
        "name": str(s.name), "dtype": str(s.dtype), "kind": kind,
        "missing": int(n - len(nonnull)), "missing_pct": round(100 * (n - len(nonnull)) / n, 2) if n else 0.0,
        "unique": unique, "unique_pct": round(100 * unique / len(nonnull), 2) if len(nonnull) else 0.0,
    }
    if kind == "numeric":
        x = pd.to_numeric(nonnull, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().astype(float)
        if len(x):
            q = x.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            counts, edges = np.histogram(x, bins=min(HIST_BINS, max(1, unique)))
            out.update(min=_num(x.min()), max=_num(x.max()), mean=_num(x.mean()), std=_num(x.std()), median=_num(q[0.5]),
                       p05=_num(q[0.05]), p25=_num(q[0.25]), p75=_num(q[0.75]), p95=_num(q[0.95]),
                       skew=_num(x.skew()) if len(x) > 2 else None, zeros=int((x == 0).sum()),
                       histogram={"edges": [_num(e) for e in edges], "counts": counts.tolist()})
    elif kind == "datetime":
        d = pd.to_datetime(nonnull, errors="coerce", format="mixed").dropna()
        if len(d):
            out.update(min=str(d.min()), max=str(d.max()))
    if kind in ("categorical", "binary", "text"):
        vc = nonnull.astype(str).value_counts()
        out["top"] = [{"value": _label(v), "count": int(c)} for v, c in vc.head(TOP_VALUES).items()]
        out["other_count"] = int(vc.iloc[TOP_VALUES:].sum())
    if kind == "text":
        lengths = nonnull.astype(str).str.len()
        out.update(length_min=int(lengths.min()), length_mean=_num(lengths.mean()), length_max=int(lengths.max()))
    return out


def resolve_target(df: pd.DataFrame, target: str | None) -> str | None:
    """An explicit target, else a column literally named 'target'. Profiling doesn't guess beyond that."""
    if target:
        if target not in df.columns:
            raise ValueError(f"Target column {target!r} isn't in the data")
        return target
    return "target" if "target" in df.columns else None


def _task(y: pd.Series) -> str:
    from athena.nodes.automl import infer_task
    return infer_task(y.dropna())


def target_summary(y: pd.Series) -> dict[str, Any]:
    task = _task(y)
    if task == "classification":
        vc = y.dropna().astype(str).value_counts()
        return {"name": str(y.name), "task": task,
                "classes": [{"value": _label(v), "count": int(c), "pct": round(100 * c / vc.sum(), 2)} for v, c in vc.head(20).items()]}
    return {"name": str(y.name), "task": task, **{k: v for k, v in column_profile(y).items() if k in ("min", "max", "mean", "std", "median", "histogram")}}


def target_association(df: pd.DataFrame, target: str, kinds: dict[str, str], excluded: set[str]) -> list[dict[str, Any]]:
    """Mutual information between each usable feature and the target, highest first."""
    from sklearn.feature_selection import mutual_info_classif, mutual_info_regression

    d = df.dropna(subset=[target])
    if len(d) > ASSOCIATION_ROWS:
        d = d.sample(ASSOCIATION_ROWS, random_state=0)
    feats = [c for c in d.columns if c != target and c not in excluded and kinds.get(c) in ("numeric", "binary", "categorical")]
    if not feats or len(d) < 10:
        return []
    X = pd.DataFrame(index=d.index)
    discrete = []
    for c in feats:
        if kinds[c] == "numeric":
            X[c] = pd.to_numeric(d[c], errors="coerce").fillna(pd.to_numeric(d[c], errors="coerce").median())
            discrete.append(False)
        else:
            X[c] = d[c].astype(str).astype("category").cat.codes
            discrete.append(True)
    y = d[target]
    if _task(y) == "classification":
        scores = mutual_info_classif(X, y.astype(str), discrete_features=discrete, random_state=0)
    else:
        scores = mutual_info_regression(X, pd.to_numeric(y, errors="coerce"), discrete_features=discrete, random_state=0)
    ranked = sorted(zip(feats, scores), key=lambda t: -t[1])
    return [{"column": c, "score": _num(s)} for c, s in ranked]


def insights(df: pd.DataFrame, cols: list[dict[str, Any]], target: str | None, duplicate_rows: int) -> list[dict[str, Any]]:
    """Data-quality findings, most important first. Each: severity, code, column (or None) and a message."""
    found: list[dict[str, Any]] = []

    def add(severity: str, code: str, column: str | None, message: str) -> None:
        found.append({"severity": severity, "code": code, "column": column, "message": message})

    n = len(df)
    for c in cols:
        name, kind = c["name"], c["kind"]
        if name == target:
            continue
        nonnull = n - c["missing"]
        if kind == "empty":
            add("warning", "empty", name, "Every value is missing: drop this column.")
            continue
        if c["unique"] <= 1:
            add("warning", "constant", name, "Has a single value, so it can't help a model: drop it.")
        if c["missing_pct"] >= 50:
            add("warning", "high_missing", name, f"{c['missing_pct']:.0f}% missing: imputing this much invents data; consider dropping it.")
        elif c["missing_pct"] >= 20:
            add("info", "missing", name, f"{c['missing_pct']:.0f}% missing: impute it (Missing Value Imputer) or add a missing-flag.")
        integer = kind == "numeric" and pd.api.types.is_integer_dtype(df[name])
        if nonnull > 20 and c["unique"] == nonnull and (integer or kind == "categorical"):  # measurements and free text are naturally all-unique
            add("warning", "id_like", name, "Every value is different, like an ID: models memorise IDs instead of learning. Drop it before training.")
        elif kind == "categorical" and c["unique"] > 50:
            add("info", "high_cardinality", name, f"{c['unique']} categories: one-hot encoding would add {c['unique']} columns; prefer label encoding or CatBoost.")
        if kind == "numeric" and c.get("skew") is not None and abs(c["skew"]) > 2:
            add("info", "skewed", name, f"Strongly skewed (skew {c['skew']:.1f}): a log transform often helps linear models.")
    if duplicate_rows:
        add("warning" if duplicate_rows / max(n, 1) > 0.05 else "info", "duplicates", None,
            f"{duplicate_rows} duplicate rows ({100 * duplicate_rows / max(n, 1):.1f}%): remove them (Duplicate Remover) so they don't leak between train and test.")
    if target:
        y = df[target]
        if y.isna().any():
            add("warning", "target_missing", target, f"The target is missing in {int(y.isna().sum())} rows: drop those rows before training.")
        if _task(y) == "classification":
            shares = y.dropna().astype(str).value_counts(normalize=True)
            if len(shares) > 1 and shares.min() < 0.2:
                add("warning", "imbalance", target, f"Imbalanced classes: the smallest class is {100 * shares.min():.1f}% of rows. "
                                                    "Use SMOTE or class weights, and judge models by F1 or ROC AUC rather than accuracy.")
        num_y = pd.to_numeric(y, errors="coerce")
        for c in cols:
            name = c["name"]
            if name == target or c["kind"] not in ("numeric", "binary"):
                continue
            x = pd.to_numeric(df[name], errors="coerce")
            both = x.notna() & num_y.notna()
            if both.sum() > 10 and x[both].nunique() > 1 and num_y[both].nunique() > 1:
                r = float(np.corrcoef(x[both], num_y[both])[0, 1])
                if abs(r) > 0.98:
                    add("warning", "leakage", name, f"Almost perfectly correlated with the target (r = {r:.3f}): it may leak the answer. "
                                                    "Check it isn't computed from the target or recorded after the outcome.")
    order = {"warning": 0, "info": 1}
    return sorted(found, key=lambda f: order[f["severity"]])


def profile_frame(df: pd.DataFrame, target: str | None = None, max_rows: int = SAMPLE_ROWS) -> dict[str, Any]:
    target = resolve_target(df, target)
    total = len(df)
    d = df.sample(max_rows, random_state=0) if total > max_rows else df
    cols = [column_profile(d[c]) for c in d.columns]
    kinds = {c["name"]: c["kind"] for c in cols}
    try:
        duplicate_rows = int(d.duplicated().sum())
    except TypeError:  # unhashable values (lists, dicts) can't be compared
        duplicate_rows = 0
    found = insights(d, cols, target, duplicate_rows)
    excluded = {f["column"] for f in found if f["code"] in ("id_like", "constant", "empty")}
    missing = int(d.isna().sum().sum())
    return {
        "overview": {
            "rows": total, "columns": len(d.columns), "profiled_rows": len(d), "sampled": total > max_rows,
            "duplicate_rows": duplicate_rows, "missing_cells": missing,
            "missing_pct": round(100 * missing / max(d.size, 1), 2),
            "memory_mb": round(float(df.memory_usage(deep=True).sum()) / 1e6, 2),
            "kinds": dict(Counter(kinds.values())),
        },
        "columns": cols,
        "insights": found,
        "target": target_summary(d[target]) if target else None,
        "association": target_association(d, target, kinds, excluded) if target else [],
    }
