"""Replay a pipeline's fitted preprocessing on new rows.

Each preprocessing node records what it learned as a plain dict (``{"kind": ..., ...}``) holding fitted
scikit-learn objects; ``apply(steps, df)`` redoes the same work on raw request rows. This file is copied verbatim
into model bundles as ``preprocess.py``, so it must stay self-contained (no Athena imports).

Columns the node saw in training but a request doesn't have (typically the target) are added as empty for the
fitted object and dropped again, so column-wise steps give exactly the training values for the other columns.
"""
from __future__ import annotations


def _padded(df, cols):
    """``df[cols]`` with any of ``cols`` it lacks added as NaN (in that order)."""
    import numpy as np
    out = df.reindex(columns=list(cols))
    for c in cols:
        if c not in df.columns:
            out[c] = np.nan
    return out


def _columns_transform(step, df):
    cols = list(step["cols"])
    if not cols:
        return df
    present = [c for c in cols if c in df.columns]
    if not present:
        return df
    values = step["transformer"].transform(_padded(df, cols))
    import pandas as pd
    out = df.copy()
    full = pd.DataFrame(values, columns=cols, index=df.index)
    for c in present:
        out[c] = full[c]
    return out


def _one_hot(step, df):
    import pandas as pd
    cols = step["cols"]
    enc = step["encoder"]
    encoded = enc.transform(_padded(df, cols))  # a missing column is unknown -> all-zero dummies (handle_unknown="ignore")
    names = enc.get_feature_names_out(cols)
    enc_df = pd.DataFrame(encoded, columns=names, index=df.index)
    return pd.concat([df.drop(columns=[c for c in cols if c in df.columns]), enc_df], axis=1)


def _label_encode(step, df):
    out = df.copy()
    for col, classes in step["classes"].items():
        if col not in out.columns:
            continue  # usually the target: not part of a request
        lookup = {c: i for i, c in enumerate(classes)}
        values = out[col].astype(str)
        unknown = sorted(set(values) - set(lookup))
        if unknown:
            raise ValueError(f"Unknown value(s) for {col!r}: {unknown[:5]} (known: {list(classes)[:10]})")
        out[col] = values.map(lookup).astype(int)
    return out


def _astype(step, df):
    import pandas as pd
    out = df.copy()
    types = {"float": float, "int": int, "str": str, "bool": bool, "float64": float, "int64": int, "string": str}
    for col, dtype in step["rules"]:
        if col not in out.columns:
            continue
        if dtype.lower() in ("datetime", "date"):
            out[col] = pd.to_datetime(out[col], errors="coerce")
        elif dtype.lower() in types:
            out[col] = out[col].astype(types[dtype.lower()])
    return out


def _select(step, df):
    cols = step["cols"]
    if step["mode"] == "include":
        return df[[c for c in cols if c in df.columns]]
    return df.drop(columns=[c for c in cols if c in df.columns])


def _poly(step, df):
    import pandas as pd
    cols = step["cols"]
    values = step["transformer"].transform(_padded(df, cols))
    names = step["transformer"].get_feature_names_out(cols)
    return pd.concat([df.drop(columns=[c for c in cols if c in df.columns]), pd.DataFrame(values, columns=names, index=df.index)], axis=1)


def _dates(step, df):
    import pandas as pd
    out = df.copy()
    col = step["col"]
    if col not in out.columns:
        raise ValueError(f"Missing date column {col!r}")
    dt = pd.to_datetime(out[col], errors="coerce")
    get = {"year": lambda: dt.dt.year, "month": lambda: dt.dt.month, "day": lambda: dt.dt.day, "weekday": lambda: dt.dt.weekday,
           "hour": lambda: dt.dt.hour, "minute": lambda: dt.dt.minute, "quarter": lambda: dt.dt.quarter,
           "week": lambda: dt.dt.isocalendar().week.astype(int), "dayofyear": lambda: dt.dt.dayofyear,
           "is_weekend": lambda: (dt.dt.weekday >= 5).astype(int)}
    for feat in step["features"]:
        if feat in get:
            out[f"{col}_{feat}"] = get[feat]()
    return out


def _text(step, df):
    import pandas as pd
    col = step["col"]
    if col not in df.columns:
        raise ValueError(f"Missing text column {col!r}")
    mat = step["vectorizer"].transform(df[col].fillna("").astype(str))
    names = [f"{col}_{n}" for n in step["vectorizer"].get_feature_names_out()]
    return pd.concat([df.drop(columns=[col]), pd.DataFrame(mat.toarray(), columns=names, index=df.index)], axis=1)


def _pca(step, df):
    import pandas as pd
    cols, target = step["cols"], step.get("target")
    comps = step["pca"].transform(_padded(df, cols).fillna(0))
    comp_df = pd.DataFrame(comps, columns=[f"pc_{i + 1}" for i in range(comps.shape[1])], index=df.index)
    rest = [c for c in df.columns if c not in cols and c != target]
    out = pd.concat([df[rest], comp_df], axis=1)
    if target and target in df.columns:
        out[target] = df[target].values
    return out


def _clip(step, df):
    """Outlier Detector (clip): the training data's bounds, per column."""
    out = df.copy()
    for col, (lo, hi) in step["bounds"].items():
        if col in out.columns:
            out[col] = out[col].clip(lo, hi)
    return out


def _outlier_flag(step, df):
    """Outlier Detector (flag): ``is_outlier`` by the method and the statistics learned in training."""
    import pandas as pd
    cols = list(step["cols"])
    num = _padded(df, cols)
    method = step["method"]
    if method == "IQR":
        mask = pd.Series(True, index=df.index)
        for col, (lo, hi) in step["bounds"].items():
            mask &= num[col].between(lo, hi)
    elif method == "Z-Score":
        filled = num.fillna(0)
        z = ((filled - pd.Series(step["mean"])) / pd.Series(step["std"])).abs()
        mask = (z < step["threshold"]).all(axis=1)
    else:  # Isolation Forest
        mask = pd.Series(step["model"].predict(num.fillna(0)) == 1, index=df.index)
    out = df.copy()
    out["is_outlier"] = (~mask).astype(int)
    return out


def _str_split(step, df):
    """String Splitter: the same separator, and exactly the columns training produced."""
    col = step["col"]
    if col not in df.columns:
        raise ValueError(f"Missing text column {col!r}")
    out = df.copy()
    if not step["expand"]:
        out[f"{col}_split"] = out[col].str.split(step["sep"])
        return out
    import pandas as pd
    parts = out[col].str.split(step["sep"], expand=True)
    parts = parts.reindex(columns=range(step["n"]))  # fewer parts than training: empty; more: dropped
    parts.columns = [f"{step['prefix']}_{i}" for i in range(step["n"])]
    return pd.concat([out, parts], axis=1)


def _lookup(step, df):
    """Data Merge: join each request row with the table the pipeline merged in (a left join, one row per request)."""
    on = list(step["on"])
    missing = [c for c in on if c not in df.columns]
    if missing:
        raise ValueError(f"Missing join key(s) {missing}")
    merged = df.merge(step["table"], on=on, how="left")
    merged.index = df.index  # the table has one row per key, so rows line up with the request
    return merged


def _features(step, df):
    """The split: the model's input columns, in training order."""
    missing = [c for c in step["columns"] if c not in df.columns]
    if missing:
        raise ValueError(f"After preprocessing, feature(s) {missing[:5]} are missing: check the request's columns")
    return df[list(step["columns"])]


_KINDS = {"columns_transform": _columns_transform, "one_hot": _one_hot, "label_encode": _label_encode, "astype": _astype,
          "select": _select, "poly": _poly, "dates": _dates, "text": _text, "pca": _pca, "features": _features,
          "clip": _clip, "outlier_flag": _outlier_flag, "str_split": _str_split, "lookup": _lookup,
          "rename": lambda step, df: df.rename(columns=step["mapping"]), "skip": lambda step, df: df}


def apply(steps, df):
    """Run every step in order. Raises ValueError with a readable message on bad input."""
    for step in steps:
        df = _KINDS[step["kind"]](step, df)
    return df
