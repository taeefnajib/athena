from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np
from sklearn.impute import SimpleImputer, KNNImputer
from sklearn.ensemble import IsolationForest

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe
from athena.schemas.artifacts import TextPreview




@node(
    "imputer", label="Missing Value Imputer", category="quality",
    description="Fill missing values using various strategies",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "strategy": ui(),
        "fill_value": ui("Fill Value"),
        "cols": ui("Columns (comma-sep)"),
    },
    code=EXPORT["imputer"],
)
class ImputerHandler:
    class Config(BaseModel):
        strategy: Literal["mean", "median", "mode", "constant", "knn"] = "mean"
        fill_value: str = "0"
        cols: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        cols = [c.strip() for c in cfg.cols.split(",") if c.strip()] if cfg.cols.strip() else None
        num_cols = df.select_dtypes(include="number").columns.tolist()
        target_cols = [c for c in (cols or num_cols) if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]

        missing_before = int(df[target_cols].isna().sum().sum()) if target_cols else 0

        if cfg.strategy == "knn":
            imp = KNNImputer()
        elif cfg.strategy == "mode":
            imp = SimpleImputer(strategy="most_frequent")
        elif cfg.strategy == "constant":
            try:
                fill: float | str = float(cfg.fill_value)
            except ValueError:
                fill = cfg.fill_value
            imp = SimpleImputer(strategy="constant", fill_value=fill)
        else:
            imp = SimpleImputer(strategy=cfg.strategy)

        if target_cols:
            df[target_cols] = imp.fit_transform(df[target_cols])

        ctx.logger.info("Imputed", cols=len(target_cols), missing_filled=missing_before)
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"missing_filled": float(missing_before)},
        )


@node(
    "dup_remover", label="Duplicate Remover", category="quality",
    description="Remove duplicate rows",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "subset": ui("Subset Columns"),
        "keep": ui(),
    },
    code=EXPORT["dup_remover"],
)
class DupRemoverHandler:
    class Config(BaseModel):
        subset: str = ""
        keep: Literal["first", "last", "none"] = "first"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        subset = [c.strip() for c in cfg.subset.split(",") if c.strip()] or None
        keep_val: Literal["first", "last"] | bool = False if cfg.keep == "none" else cfg.keep
        before = len(df)
        df = df.drop_duplicates(subset=subset, keep=keep_val)
        removed = before - len(df)
        ctx.logger.info("Removed duplicates", removed=removed)
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"removed": float(removed), "remaining": float(len(df))},
        )


@node(
    "outlier", label="Outlier Detector", category="quality",
    description="Detect and handle outliers in selected numeric columns",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset"), Port("outliers", "outliers")],
    fields={
        "method": ui(),
        "action": ui(),
        "threshold": ui("Threshold (Z-Score)"),
        "cols": ui("Columns (comma-sep, blank = all numeric)"),
        "col_mode": ui("Column Mode"),
    },
    code=EXPORT["outlier"],
)
class OutlierHandler:
    class Config(BaseModel):
        method: Literal["IQR", "Z-Score", "Isolation Forest"] = "IQR"
        action: Literal["remove", "clip", "flag"] = "remove"
        threshold: float = 3.0
        cols: str = ""
        col_mode: Literal["include", "exclude"] = "include"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        all_num_cols = df.select_dtypes(include="number").columns.tolist()

        specified = [c.strip() for c in cfg.cols.split(",") if c.strip()]
        if specified:
            if cfg.col_mode == "include":
                num_cols = [c for c in specified if c in all_num_cols]
            else:
                num_cols = [c for c in all_num_cols if c not in specified]
        else:
            num_cols = all_num_cols

        if not num_cols:
            ctx.logger.warning("No numeric columns to check for outliers after column filter")
            return HandlerResult(
                outputs=[df, df.iloc[0:0]],
                preview=preview_dataframe(df),
                metrics={"outliers_found": 0.0, "remaining": float(len(df))},
            )

        if cfg.method == "IQR":
            mask = pd.Series(True, index=df.index)
            for col in num_cols:
                q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
                iqr = q3 - q1
                mask &= df[col].between(q1 - 1.5 * iqr, q3 + 1.5 * iqr)
        elif cfg.method == "Z-Score":
            filled = df[num_cols].fillna(0)
            std = filled.std().replace(0, 1)
            z = ((filled - filled.mean()) / std).abs()
            mask = (z < cfg.threshold).all(axis=1)
        else:  # Isolation Forest
            clf = IsolationForest(contamination=0.1, random_state=42)
            preds = clf.fit_predict(df[num_cols].fillna(0))
            mask = pd.Series(preds == 1, index=df.index)

        outlier_rows = df[~mask]

        if cfg.action == "remove":
            result = df[mask]
        elif cfg.action == "clip":
            result = df.copy()
            for col in num_cols:
                q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
                iqr = q3 - q1
                result[col] = df[col].clip(q1 - 1.5 * iqr, q3 + 1.5 * iqr)
        else:  # flag
            result = df.copy()
            result["is_outlier"] = (~mask).astype(int)

        n_outliers = int((~mask).sum())
        ctx.logger.info("Outlier detection", method=cfg.method, action=cfg.action, outliers=n_outliers)
        return HandlerResult(
            outputs=[result, outlier_rows],
            preview=preview_dataframe(result),
            metrics={"outliers_found": float(n_outliers), "remaining": float(len(result))},
        )


@node(
    "col_rename", label="Column Renamer", category="quality",
    description="Rename one or more columns",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "mappings": ui("Rename Mappings", widget="col_map"),
    },
    code=EXPORT["col_rename"],
)
class ColRenameHandler:
    class Config(BaseModel):
        mappings: list[dict[str, str]] = []

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()

        rename_map: dict[str, str] = {}
        errors: list[str] = []
        for entry in cfg.mappings:
            old = entry.get("key", "").strip()
            new = entry.get("values", "").strip()
            if not old or not new:
                continue
            if old not in df.columns:
                errors.append(f"Column '{old}' not found")
                continue
            rename_map[old] = new

        if errors:
            ctx.logger.warning("Some columns not found", errors=errors)

        df = df.rename(columns=rename_map)
        ctx.logger.info("Renamed columns", count=len(rename_map))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"renamed": float(len(rename_map))},
        )


@node(
    "type_conv", label="Type Converter", category="quality",
    description="Convert column data types",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "rules": ui("Conversion Rules", widget="textarea"),
    },
    code=EXPORT["type_conv"],
)
class TypeConvHandler:
    class Config(BaseModel):
        rules: str = "col1: float\ncol2: int"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        type_map: dict[str, object] = {
            "float": float, "int": int, "str": str, "bool": bool,
            "float64": float, "int64": int, "string": str,
        }
        converted = 0
        errors: list[str] = []
        for line in cfg.rules.splitlines():
            if ":" not in line:
                continue
            col, dtype = (p.strip() for p in line.split(":", 1))
            if col not in df.columns:
                errors.append(f"Column '{col}' not found")
                continue
            try:
                if dtype.lower() in ("datetime", "date"):
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                else:
                    target = type_map.get(dtype.lower())
                    if target:
                        df[col] = df[col].astype(target)  # type: ignore[arg-type]
                converted += 1
            except Exception as e:
                errors.append(f"{col}: {e}")
        if errors:
            ctx.logger.warn("Some conversions failed", errors=errors)
        ctx.logger.info("Type conversion done", converted=converted)
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"converted": float(converted)},
        )


@node(
    "validator", label="Data Validator", category="quality",
    description="Enforce schema and constraints",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset"), Port("report", "report")],
    fields={
        "schema": ui("Schema (JSON)", widget="textarea"),
        "strict": ui("Strict Mode"),
    },
    code=EXPORT["validator"],
)
class ValidatorHandler:
    class Config(BaseModel):
        schema: str = '{"col1": "float", "col2": "str"}'
        strict: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import json
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        try:
            schema: dict[str, str] = json.loads(cfg.schema)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid schema JSON: {e}")

        issues: list[str] = []
        for col, expected in schema.items():
            if col not in df.columns:
                issues.append(f"Missing column: {col}")
            elif expected in ("float", "int", "number") and not pd.api.types.is_numeric_dtype(df[col]):
                issues.append(f"'{col}' expected numeric, got {df[col].dtype}")
            elif expected in ("str", "string", "object") and not pd.api.types.is_object_dtype(df[col]):
                issues.append(f"'{col}' expected string, got {df[col].dtype}")

        if cfg.strict and issues:
            raise ValueError(f"Validation failed: {'; '.join(issues)}")

        ctx.logger.info("Validated", checked=len(schema), issues=len(issues))
        summary = (
            f"Checked {len(schema)} columns — {len(issues)} issue(s)\n" + "\n".join(issues)
            if issues else f"✓ All {len(schema)} columns passed validation"
        )
        report: dict = {"issues": issues, "columns_checked": len(schema), "issues_found": len(issues)}
        return HandlerResult(
            outputs=[df, report],
            preview=TextPreview(text=summary),
            metrics={"issues_found": float(len(issues))},
        )
