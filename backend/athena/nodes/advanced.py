import re
from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe
from athena.schemas.artifacts import ModelPreview, TextPreview


def _cast(s: str) -> object:
    s = s.strip()
    if s.lower() in ("none", "null"):
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_values(spec: str) -> list:
    """Parse a value spec string into a list.

    Supports: "1,2,10" → [1,2,10]; "1-50" → range; "1-50,100" → range + extras.
    """
    result: list = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r'(\d+)-(\d+)', part)
        if m:
            result.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        else:
            result.append(_cast(part))
    return result


@node(
    "hp_tune", label="HP Tuning Config", category="advanced",
    description="Emit a hyperparameter search config to connect to any model node",
    outputs=[Port("hp_config", "hpconfig")],
    fields={
        "method": ui(help="Optuna samples smartly (TPE): a value list of more than three numbers, such as 10-200, is searched as a range. Needs the optuna extra."),
        "scoring": ui("Scoring Metric", widget="select", options=["accuracy", "f1_weighted", "f1_macro", "roc_auc", "r2", "neg_root_mean_squared_error", "neg_mean_absolute_error"]),
        "n_iter": ui("Iterations / trials (not Grid)", min=1),
        "cv": ui("CV Folds", min=2),
        "n_jobs": ui("Parallel Jobs (-1 = all cores)", min=-1),
        "params": ui("Parameter Grid", widget="hp_params"),
    },
    code=EXPORT["hp_tune"],
)
class HpTuneHandler:
    class Config(BaseModel):
        method: Literal["Grid", "Random", "Bayesian", "Optuna"] = "Random"
        scoring: str = "accuracy"
        n_iter: int = 25
        cv: int = 5
        n_jobs: int = -1
        params: list[dict] = []

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)

        param_grid: dict[str, list] = {}
        for row in cfg.params:
            key = str(row.get("key", "")).strip()
            values_spec = str(row.get("values", "")).strip()
            if key and values_spec:
                param_grid[key] = _parse_values(values_spec)

        hpconfig = {
            "method": cfg.method,
            "scoring": cfg.scoring,
            "n_iter": cfg.n_iter,
            "cv": cfg.cv,
            "n_jobs": cfg.n_jobs,
            "param_grid": param_grid,
        }

        lines = [
            f"Method: {cfg.method}",
            f"Scoring: {cfg.scoring}",
            f"CV Folds: {cfg.cv}",
            f"Parallel jobs: {cfg.n_jobs if cfg.n_jobs != -1 else 'all cores'}",
        ]
        if cfg.method != "Grid":
            lines.append(f"Iterations: {cfg.n_iter}")
        lines.append("")
        lines.append("Parameter grid:")
        if param_grid:
            for k, v in param_grid.items():
                preview_vals: list = v if len(v) <= 5 else v[:5] + ["…"]
                lines.append(f"  {k}: {preview_vals}")
        else:
            lines.append("  (no parameters configured — add rows in Settings)")

        ctx.logger.info("HP tune config emitted", method=cfg.method, scoring=cfg.scoring, params=list(param_grid.keys()))
        return HandlerResult(
            outputs=[hpconfig],
            preview=TextPreview(text="\n".join(lines)),
        )


@node(
    "pipeline_wrap", label="Pipeline Wrapper", category="advanced",
    description="Wrap preprocessing + model into a pipeline",
    inputs=[Port("dataset", "dataset"), Port("model", "model")],
    outputs=[Port("pipeline", "pipeline")],
    fields={
        "memory": ui("Cache Pipeline"),
    },
    code=EXPORT["pipeline_wrap"],
)
class PipelineWrapHandler:
    class Config(BaseModel):
        memory: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.pipeline import Pipeline
        df: pd.DataFrame = ctx.inputs[0]
        model = ctx.inputs[1]
        pipe = Pipeline(steps=[("model", model)], memory="pipeline_cache" if ctx.config.get("memory") else None)
        ctx.logger.info("Pipeline wrapped", steps=len(pipe.steps))
        return HandlerResult(
            outputs=[pipe],
            preview=ModelPreview(summary=repr(pipe)),
        )


@node(
    "custom_code", reusable=False, label="Custom Code Node", category="advanced",
    description="Execute custom Python snippet",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "code": ui("Python Code", widget="textarea", mono=True),
    },
    code=EXPORT["custom_code"],
)
class CustomCodeHandler:
    class Config(BaseModel):
        code: str = "# df is your DataFrame\ndf['new_col'] = df['col1'] * 2\nreturn df"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from athena.config import settings
        if not settings.allow_custom_code:
            raise ValueError("Custom code is disabled (ATHENA_ALLOW_CUSTOM_CODE=false).")
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        lines = ["def _user_fn(df, pd, np):"] + [f"    {ln}" for ln in cfg.code.splitlines()]
        src = "\n".join(lines)
        namespace: dict = {}
        try:
            exec(src, namespace)  # noqa: S102
            result = namespace["_user_fn"](df, pd, np)
        except Exception as e:
            raise ValueError(f"Custom code error: {e}") from e
        if not isinstance(result, pd.DataFrame):
            raise ValueError("Custom code must return a pandas DataFrame")
        ctx.logger.info("Custom code executed", output_rows=len(result), output_cols=len(result.columns))
        return HandlerResult(outputs=[result], preview=preview_dataframe(result))


