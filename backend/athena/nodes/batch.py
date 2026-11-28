"""Batch Predict: score a whole table with a packaged model (a Serving bundle), its preprocessing included.

The bundle's own `preprocess.py` and `preprocessing.joblib` run first, then `model.joblib`, exactly what its endpoint
does per request, so raw rows go in. Put it after a loader (or SQL Query, Endpoint Requests…) and before CSV Export,
then schedule the pipeline for recurring batch scoring. ``_athena_bundle_predict`` is self-contained and copied
verbatim into exported scripts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from athena.config import settings
from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe


def _athena_bundle_predict(folder, df, probabilities=True, keep_columns=True):
    """Predict every row of ``df`` with the model bundle in ``folder`` (made by Athena's Serving): the bundle's
    preprocessing (preprocess.py + preprocessing.joblib), then its model. Adds ``prediction`` and, for classifiers,
    one ``proba_<class>`` column per class."""
    import importlib.util
    import json
    from pathlib import Path

    import joblib
    import pandas as pd
    folder = Path(folder)
    schema = json.loads((folder / "schema.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("_athena_bundle_preprocess", folder / "preprocess.py")
    preprocess = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preprocess)
    model = joblib.load(folder / "model.joblib")
    steps = joblib.load(folder / "preprocessing.joblib")
    features = [f["name"] for f in schema["features"]]
    missing = [c for c in features if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature(s) {missing[:10]}: the model expects {features}")
    X = df[features].copy()
    for f in schema["features"]:
        if f["kind"] in ("number", "boolean"):
            X[f["name"]] = pd.to_numeric(X[f["name"]])
    X = preprocess.apply(steps, X)
    out = df.copy() if keep_columns else pd.DataFrame(index=df.index)
    out["prediction"] = model.predict(X)
    if probabilities and schema["task"] == "classification" and hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        for i, c in enumerate(model.classes_):
            name = int(c) if isinstance(c, float) and c.is_integer() else c  # proba_1, not proba_1.0
            out[f"proba_{name}"] = proba[:, i]
    return out


def bundle_folder(model: str, check: bool = True) -> Path:
    from athena.serving.bundle import slugify
    if not check:  # export: where the bundle lives, whether or not it exists yet
        return settings.data_dir / "models" / (slugify(model) if model.strip() else "YOUR-MODEL")
    if not model.strip():
        raise ValueError("Choose the packaged model to predict with (its name in Serving)")
    path = settings.data_dir / "models" / slugify(model)
    if not (path / "schema.json").exists():
        models = sorted(p.name for p in (settings.data_dir / "models").glob("*") if (p / "schema.json").exists())
        raise ValueError(f"No packaged model named {model!r}." + (f" Packaged: {', '.join(models)}" if models else " Deploy one first (Serving)."))
    return path


@node(
    "batch_predict", label="Batch Predict", category="deploy",
    description="Score a table with a packaged model (Serving), its preprocessing included: raw rows in, predictions out",
    inputs=[Port("dataset", "dataset")], outputs=[Port("predictions", "dataset")],
    fields={"model": ui("Packaged model (its name in Serving)"), "probabilities": ui("Add class probabilities"),
            "keep_columns": ui("Keep the input columns")},
    code=EXPORT["batch_predict"],
    reusable=False,  # the bundle can be re-packaged under the same name: always score with the current one
)
class BatchPredictHandler:
    class Config(BaseModel):
        model: str = ""
        probabilities: bool = True
        keep_columns: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        folder = bundle_folder(cfg.model)
        out = _athena_bundle_predict(folder, df, cfg.probabilities, cfg.keep_columns)
        metrics: dict[str, float] = {"rows": float(len(out))}
        task = json.loads((folder / "schema.json").read_text(encoding="utf-8")).get("task")
        counts = out["prediction"].value_counts()
        if task == "classification" and len(counts) <= 20:
            metrics.update({f"predicted_{int(k) if isinstance(k, float) and k.is_integer() else k}": float(v) for k, v in counts.items()})
        else:
            metrics["prediction_mean"] = float(pd.to_numeric(out["prediction"]).mean())
        ctx.logger.info(f"Scored {len(out):,} row(s) with {folder.name}")
        return HandlerResult(outputs=[out], preview=preview_dataframe(out), metrics=metrics)
