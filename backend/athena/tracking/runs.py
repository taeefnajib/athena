"""Read run history from MLflow, shaped for the Runs view and for comparing runs side by side."""
from __future__ import annotations

from typing import Any


def list_runs(client: Any, experiment_name: str, limit: int = 100) -> list[dict[str, Any]]:
    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        return []
    runs = client.search_runs([exp.experiment_id], max_results=limit, order_by=["attributes.start_time DESC"])
    out = []
    for r in runs:
        info, data = r.info, r.data
        end = info.end_time
        out.append({
            "run_id": info.run_id,
            "name": info.run_name,
            "status": info.status,
            "start_time": info.start_time,
            "duration_ms": (end - info.start_time) if end and info.start_time else None,
            "metrics": dict(data.metrics),
            "params": dict(data.params),
            "athena_run_id": data.tags.get("athena.run_id"),
            "pipeline": data.tags.get("athena.pipeline"),
            "node_labels": data.tags.get("athena.node_labels"),
        })
    return out


def runs_frame(client: Any, experiment_name: str, limit: int | None = None) -> Any:
    import pandas as pd

    rows = []
    for r in list_runs(client, experiment_name, limit or 1000):
        row = {"run_id": r["run_id"], "name": r["name"], "status": r["status"], "start_time": r["start_time"]}
        row.update({f"metrics.{k}": v for k, v in r["metrics"].items()})
        row.update({f"params.{k}": v for k, v in r["params"].items()})
        rows.append(row)
    return pd.DataFrame(rows)
