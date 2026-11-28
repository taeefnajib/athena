"""Endpoint Requests: the rows a local endpoint received (its request log), as a table.

Connect it as the *current* input of Data Drift Report or Prediction Drift, with the training data as the reference,
to see whether live traffic still looks like what the model learned from. ``_athena_endpoint_requests`` is
self-contained and copied verbatim into exported scripts.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from athena.config import settings
from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.utils.dataframes import preview_dataframe


def _athena_endpoint_requests(folder, last_n=0, include_prediction=True):
    """The rows a deployed endpoint logged (requests.1.jsonl, then requests.jsonl): its features as received,
    the prediction and a UTC timestamp. ``last_n`` keeps only the most recent rows (0 = all)."""
    import json
    from pathlib import Path

    import pandas as pd
    folder = Path(folder)
    records = []
    for f in (folder / "requests.1.jsonl", folder / "requests.jsonl"):
        if f.exists():
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        records.append(json.loads(line))
                    except ValueError:  # a line still being written
                        continue
    if not records:
        raise ValueError(f"No requests logged in {folder} yet: start the endpoint (Serving) and send it some predictions")
    df = pd.DataFrame.from_records(records)
    if last_n:
        df = df.tail(int(last_n)).reset_index(drop=True)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    if not include_prediction:
        df = df.drop(columns=["prediction"], errors="ignore")
    return df


def request_folder(model: str, check: bool = True) -> Path:
    from athena.serving.bundle import slugify
    if not check:  # export: the path the endpoint logs to, whether or not it's deployed yet
        return settings.data_dir / "models" / (slugify(model) if model.strip() else "YOUR-MODEL") / "logs"
    if not model.strip():
        raise ValueError("Choose the deployed model whose requests to read")
    path = settings.data_dir / "models" / slugify(model)
    if not (path / "schema.json").exists():
        models = sorted(p.name for p in (settings.data_dir / "models").glob("*") if (p / "schema.json").exists())
        raise ValueError(f"No deployed model named {model!r}." + (f" Deployed: {', '.join(models)}" if models else " Deploy one first."))
    return path / "logs"


@node(
    "endpoint_requests", label="Endpoint Requests", category="monitor",
    description="The rows a local endpoint received (with their predictions): compare them with the training data for drift",
    inputs=[], outputs=[Port("dataset", "dataset")],
    fields={"model": ui("Deployed model (its name in Serving)"), "last_n": ui("Most recent rows (0 = all)"),
            "include_prediction": ui("Include the prediction column")},
    code=EXPORT["endpoint_requests"],
    reusable=False,  # a live source: always re-read
)
class EndpointRequestsHandler:
    class Config(BaseModel):
        model: str = ""
        last_n: int = Field(0, ge=0)
        include_prediction: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = _athena_endpoint_requests(request_folder(cfg.model), cfg.last_n, cfg.include_prediction)
        span = ""
        if "timestamp" in df.columns and len(df):
            span = f" from {df['timestamp'].min():%Y-%m-%d %H:%M} to {df['timestamp'].max():%Y-%m-%d %H:%M} UTC"
        ctx.logger.info(f"{len(df)} logged request row(s){span}")
        return HandlerResult(outputs=[df], preview=preview_dataframe(df), metrics={"rows": float(len(df))})
