"""Export template: Batch Predict. It calls ``_athena_bundle_predict`` (copied verbatim), which loads the packaged
model from its bundle folder, so the script needs that folder (Serving → Download .zip, unzipped at the same path or
the path below edited)."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]


def batch_predict(v: V) -> str:
    from athena.nodes.batch import bundle_folder
    folder = str(bundle_folder(str(v["model"]), check=False))
    return lines(
        f"MODEL_DIR_{v['var']} = {folder!r}  # the packaged model (Serving bundle); edit if you moved it",
        f"{v['out_predictions']} = _athena_bundle_predict(MODEL_DIR_{v['var']}, {v['in_dataset']}, "
        f"{bool(v['probabilities'])!r}, {bool(v['keep_columns'])!r})",
        f"print({v['out_predictions']}.head())",
    )


EXPORT: dict[str, Template] = {"batch_predict": batch_predict}
