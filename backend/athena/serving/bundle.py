"""Model bundles: a trained model from a run, packaged to serve without Athena.

``<data_dir>/models/<slug>/`` holds model.joblib, schema.json (features, kinds, an example row), service.py
(FastAPI), requirements.txt (the packages the pickled model needs, pinned), a Dockerfile, BentoML files, an
example request and a README.
"""
from __future__ import annotations

import io
import json
import pickle
import re
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import pandas as pd

from athena.config import settings
from athena.core.registry import NODE_META
from athena.core.subflows import expand
from athena.schemas.pipeline import PipelineSpec
from athena.serving import templates

BASE_REQUIREMENTS = ("fastapi", "uvicorn", "pandas", "numpy", "joblib", "pydantic")


class BundleError(ValueError):
    pass


def models_dir() -> Path:
    d = settings.data_dir / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise BundleError("Give the model a name")
    return slug[:60]


def _input_edge(spec: PipelineSpec, node_id: str, port_type: str) -> tuple[str, int] | None:
    meta = NODE_META.get(spec.node(node_id).type)
    if meta is None:
        return None
    for i, p in enumerate(meta.inputs):
        if p.type == port_type:
            e = next((e for e in spec.edges if e.target == node_id and e.target_port == i), None)
            if e:
                return e.source, e.source_port
    return None


def training_source(spec: PipelineSpec, node_id: str) -> tuple[str, int]:
    """Where the model's training features came from: its X_train input, following model inputs (Pipeline
    Wrapper, Calibration, Decision Threshold...) back to the estimator that was fitted."""
    seen: set[str] = set()
    current = node_id
    while current not in seen:
        seen.add(current)
        if (src := _input_edge(spec, current, "X_train")) is not None:
            return src
        model_src = _input_edge(spec, current, "model")
        if model_src is None:
            break
        current = model_src[0]
    raise BundleError("Couldn't find the training data for this model (no X_train input upstream)")


def feature_schema(X: pd.DataFrame) -> list[dict[str, Any]]:
    """Each feature's name, kind and a typical value (median / most frequent: never a real row)."""
    out = []
    for c in X.columns:
        s = X[c].dropna()
        if pd.api.types.is_bool_dtype(X[c]):
            kind, example = "boolean", bool(s.mode().iloc[0]) if len(s) else False
        elif pd.api.types.is_numeric_dtype(X[c]):
            kind = "number"
            example = round(float(s.median()), 6) + 0.0 if len(s) else 0.0  # no float noise like -1.98e-16 (+0.0 drops -0.0)
            if pd.api.types.is_integer_dtype(X[c]):
                example = round(example)
        else:
            kind, example = "category", str(s.mode().iloc[0]) if len(s) else ""
        out.append({"name": str(c), "kind": kind, "dtype": str(X[c].dtype), "example": example})
    return out


def requirements_for(model: Any) -> tuple[list[str], bool]:
    """Pinned packages the pickled model needs (plus the service's own), and whether it needs Athena itself."""
    roots: set[str] = set()

    class Recorder(pickle.Unpickler):
        def find_class(self, module: str, name: str) -> Any:
            roots.add(module.split(".")[0])
            return super().find_class(module, name)

    Recorder(io.BytesIO(pickle.dumps(model))).load()
    dists = metadata.packages_distributions()
    needed = {d for r in roots if r not in sys.stdlib_module_names and r != "builtins" for d in dists.get(r, [])}
    needed |= set(BASE_REQUIREMENTS)
    needs_athena = "athena" in roots
    needed.discard("athena-backend")
    reqs = []
    for dist in sorted(needed, key=str.lower):
        try:
            reqs.append(f"{dist}=={metadata.version(dist)}")
        except metadata.PackageNotFoundError:
            reqs.append(dist)
    return reqs, needs_athena


def build_bundle(name: str, model: Any, X: pd.DataFrame, info: dict[str, Any], steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Write the bundle; replaces an earlier bundle with the same name. ``X`` is what requests look like (raw columns
    when the preprocessing is replayed); ``steps`` turn it into the model's features (replay_core)."""
    import inspect

    import joblib

    from athena.serving import replay_core
    steps = steps or [{"kind": "features", "columns": [str(c) for c in X.columns]}]

    if not hasattr(model, "predict"):
        raise BundleError(f"A {type(model).__name__} can't make predictions, so it can't be served")
    slug = slugify(name)
    target = models_dir() / slug
    tmp = models_dir() / f".{slug}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    features = feature_schema(X)
    task = "classification" if hasattr(model, "classes_") else "regression"
    reqs, needs_athena = requirements_for([model, steps])
    version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    schema = {"name": name, "model": type(model).__name__, "version": version, "task": task, "features": features,
              "classes": [c.item() if hasattr(c, "item") else c for c in getattr(model, "classes_", [])],
              "source": {k: info.get(k) for k in ("pipeline", "node_id", "node_label", "run_id")},
              "model_features": steps[-1]["columns"], "preprocessing_not_included": info.get("preprocessing", []),
              "preprocessing_replayed": info.get("replayed", []), "training_only": info.get("training_only", []),
              "preprocessing_verified": info.get("verified", False), "preprocessing_note": info.get("note", ""), "needs_athena": needs_athena,
              "evaluation": info.get("evaluation", []), "quality_gates": info.get("quality_gates", [])}
    joblib.dump(model, tmp / "model.joblib")
    joblib.dump(steps, tmp / "preprocessing.joblib")
    (tmp / "preprocess.py").write_text(inspect.getsource(replay_core), encoding="utf-8")
    (tmp / "schema.json").write_text(json.dumps(schema, indent=2, default=str), encoding="utf-8")
    from athena.serving.card import model_card
    (tmp / "MODEL_CARD.md").write_text(model_card(schema, info.get("rows", len(X))), encoding="utf-8")
    (tmp / "example.json").write_text(json.dumps({"rows": [{f["name"]: f["example"] for f in features}]}, indent=2), encoding="utf-8")
    (tmp / "requirements.txt").write_text("\n".join(reqs) + "\n", encoding="utf-8")
    (tmp / "service.py").write_text(templates.SERVICE.format(name=name), encoding="utf-8")
    (tmp / "service_bentoml.py").write_text(templates.BENTO_SERVICE.format(slug=slug), encoding="utf-8")
    (tmp / "bentofile.yaml").write_text(templates.BENTOFILE, encoding="utf-8")
    (tmp / "Dockerfile").write_text(templates.DOCKERFILE.format(slug=slug, python=f"{sys.version_info.major}.{sys.version_info.minor}"), encoding="utf-8")
    pre = info.get("preprocessing") or []
    (tmp / "README.md").write_text(templates.README.format(
        name=name, slug=slug, node_label=info.get("node_label", ""), pipeline=info.get("pipeline", ""), run_id=info.get("run_id", ""),
        task=task, n_features=len(features),
        preprocessing_note=((f"- **Send preprocessed features.** These upstream steps are not part of the service: {', '.join(pre)}. "
                             "Apply them to requests yourself (as the pipeline did before training).\n") if pre else
                            (f"- Takes **raw rows**: the service replays the pipeline's fitted preprocessing ({', '.join(info.get('replayed') or [])}) "
                             "before predicting.\n") if info.get("replayed") else ""),
        athena_note=("\n**Needs Athena's wrapper classes:** this model was built by an Athena node with its own estimator class, "
                     "so `pip install athena-backend` as well.\n") if needs_athena else ""), encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return describe(target)


def describe(path: Path) -> dict[str, Any]:
    schema = json.loads((path / "schema.json").read_text(encoding="utf-8"))
    lists = ("preprocessing_not_included", "preprocessing_replayed", "training_only")
    return {"name": schema["name"], "slug": path.name, "path": str(path), "model": schema["model"], "task": schema["task"],
            "version": schema["version"], "features": schema["features"], "classes": schema.get("classes", []),
            "source": schema.get("source", {}), "needs_athena": schema.get("needs_athena", False),
            "preprocessing_verified": schema.get("preprocessing_verified", False),
            "preprocessing_note": schema.get("preprocessing_note", ""), **{k: schema.get(k, []) for k in lists},
            "evaluation": schema.get("evaluation", []), "quality_gates": schema.get("quality_gates", [])}


def list_bundles() -> list[dict[str, Any]]:
    out = []
    for p in sorted(models_dir().iterdir()):
        if p.is_dir() and not p.name.startswith(".") and (p / "schema.json").exists():
            try:
                out.append(describe(p))
            except (ValueError, KeyError):
                continue
    return out


def bundle_path(slug: str) -> Path:
    path = models_dir() / slugify(slug)
    if not (path / "schema.json").exists():
        raise BundleError(f"No model bundle named {slug!r}")
    return path


def zip_bundle(slug: str) -> bytes:
    path = bundle_path(slug)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(path.iterdir()):
            if f.is_file() and f.name != "endpoint.log":
                z.write(f, f"{path.name}/{f.name}")
    return buf.getvalue()


def bundle_from_run(name: str, spec: PipelineSpec, run_id: str, node_id: str, port: int) -> dict[str, Any]:
    from athena.core.artifacts import load_output
    flat, _ = expand(spec)
    try:
        flat.node(node_id)
    except KeyError as exc:
        raise BundleError(f"Node {node_id!r} isn't in this pipeline") from exc
    model = load_output(run_id, node_id, port)
    src, src_port = training_source(flat, node_id)
    X = load_output(run_id, src, src_port)
    if isinstance(X, pd.Series):
        X = X.to_frame()
    if not isinstance(X, pd.DataFrame):
        raise BundleError("The model's training data isn't a table")
    from athena.serving.card import gather_evidence
    from athena.serving.chain import build_chain
    chain = build_chain(flat, run_id, src, X)
    meta = NODE_META.get(flat.node(node_id).type)
    info = {"pipeline": spec.name, "node_id": node_id, "node_label": meta.label if meta else node_id, "run_id": run_id,
            "preprocessing": chain.not_replayed, "replayed": chain.replayed, "training_only": chain.training_only,
            "verified": chain.verified, "note": chain.note, "rows": len(X), **gather_evidence(flat, run_id, node_id)}
    return build_bundle(name, model, chain.raw, info, chain.steps)
