"""Dataset Snapshot: save a content-hashed Parquet copy of a table, so a run's exact data can be found again.

The file name carries a hash of the table's columns, types and values: the same data always maps to the same
file (written once), and any change gives a new one. Read it back with the Parquet Loader.
"""
from __future__ import annotations

from pydantic import BaseModel

from athena.config import settings
from athena.core.handler import ExecutionContext, HandlerResult
from athena.nodes.export import EXPORT
from athena.schemas.artifacts import TextPreview
from athena.sdk import Port, node, ui


def _athena_snapshot(df, folder, name=""):
    """Write ``df`` to ``<folder>/<name>-<hash>.parquet`` unless that file exists. Returns (path, hash)."""
    import hashlib
    import os

    import pandas as pd
    h = hashlib.sha256("|".join(f"{c}:{t}" for c, t in zip(map(str, df.columns), map(str, df.dtypes))).encode())
    try:
        rows = pd.util.hash_pandas_object(df, index=False)
    except TypeError:  # unhashable cells (lists, dicts): hash their text form
        rows = pd.util.hash_pandas_object(df.astype(str), index=False)
    h.update(rows.to_numpy().tobytes())
    digest = h.hexdigest()[:16]
    os.makedirs(folder, exist_ok=True)
    stem = f"{name.strip()}-{digest}" if str(name).strip() else digest
    path = os.path.join(folder, f"{stem}.parquet")
    if not os.path.exists(path):
        df.to_parquet(path + ".tmp", index=False)
        os.replace(path + ".tmp", path)  # atomic: a half-written snapshot never carries a valid name
    return path, digest


def default_folder() -> str:
    return str(settings.data_dir / "snapshots")


@node(
    "dataset_snapshot", reusable=False, label="Dataset Snapshot", category="data",
    description="Save a content-hashed Parquet copy of the table (same data, same file) and pass the table on",
    inputs=[Port("dataset", "dataset")], outputs=[Port("dataset", "dataset")],
    fields={"folder": ui("Folder", help="Empty = Athena's snapshots folder (~/.athena/snapshots)."),
            "name": ui("Name", help="Optional prefix for the file name, e.g. training-data.")},
    code=EXPORT["dataset_snapshot"],
)
class DatasetSnapshotHandler:
    class Config(BaseModel):
        folder: str = ""
        name: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df = ctx.inputs[0]
        folder = cfg.folder.strip() or default_folder()
        path, digest = _athena_snapshot(df, folder, cfg.name)
        ctx.logger.info("Snapshot", hash=digest, path=path)
        ctx.logger.info("Read it back with the Parquet Loader. The hash changes whenever the data does.")
        return HandlerResult(
            outputs=[df],
            preview=TextPreview(text=f"Snapshot {digest}: {len(df):,} rows × {df.shape[1]} columns\n{path}"),
            metrics={"rows": float(len(df)), "columns": float(df.shape[1])},
        )
