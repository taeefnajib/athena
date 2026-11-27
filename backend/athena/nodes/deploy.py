from pydantic import BaseModel
from typing import Literal
import base64
import pandas as pd
import joblib
import pickle
from pathlib import Path

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe
from athena.schemas.artifacts import TextPreview, DataframePreview
from athena.config import settings


@node(
    "csv_export", label="CSV Export", category="deploy",
    description="Save dataset to CSV file",
    inputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("Output Path"),
        "index": ui("Include Index"),
    },
    code=EXPORT["csv_export"],
)
class CsvExportHandler:
    class Config(BaseModel):
        path: str = "output.csv"
        index: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        out_path = Path(cfg.path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=cfg.index)
        ctx.logger.info("Exported CSV", path=str(out_path), rows=len(df))
        return HandlerResult(
            outputs=[],
            preview=TextPreview(text=f"Saved {len(df):,} rows × {len(df.columns)} cols → {out_path}"),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@node(
    "model_saver", label="Model Saver", category="deploy",
    description="Serialize model with pickle/joblib",
    inputs=[Port("model", "model")],
    fields={
        "path": ui("Save Path"),
        "format": ui(),
    },
    code=EXPORT["model_saver"],
)
class ModelSaverHandler:
    class Config(BaseModel):
        path: str = "model.pkl"
        format: Literal["joblib", "pickle"] = "joblib"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        out_path = Path(cfg.path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if cfg.format == "joblib":
            joblib.dump(model, out_path)
        else:
            with open(out_path, "wb") as f:
                pickle.dump(model, f)
        ctx.logger.info("Model saved", path=str(out_path), format=cfg.format)
        return HandlerResult(
            outputs=[],
            preview=TextPreview(text=f"Model saved → {out_path} ({cfg.format})"),
        )


@node(
    "predict", label="Prediction Node", category="deploy",
    description="Batch prediction on new data",
    inputs=[Port("model", "model"), Port("dataset", "dataset")],
    outputs=[Port("predictions", "predictions")],
    fields={
        "output_col": ui("Output Column"),
        "proba": ui("Return Probabilities"),
    },
    code=EXPORT["predict"],
)
class PredictHandler:
    class Config(BaseModel):
        output_col: str = "y_pred"
        proba: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        df: pd.DataFrame = ctx.inputs[1].copy()
        ctx.logger.info("Running predictions", rows=len(df), proba=cfg.proba)
        if cfg.proba and hasattr(model, "predict_proba"):
            proba = model.predict_proba(df)
            classes = getattr(model, "classes_", range(proba.shape[1]))
            for i, cls in enumerate(classes):
                df[f"{cfg.output_col}_proba_{cls}"] = proba[:, i]
        else:
            df[cfg.output_col] = model.predict(df)
        ctx.logger.info("Predictions done", rows=len(df))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df))},
        )


@node(
    "report_gen", label="Report Generator", category="deploy",
    description="Generate PDF/HTML/Jupyter summary report",
    inputs=[Port("report", "report")],
    fields={
        "format": ui(),
        "path": ui("Output Path"),
    },
    code=EXPORT["report_gen"],
)
class ReportGenHandler:
    class Config(BaseModel):
        format: Literal["HTML", "PDF", "Jupyter"] = "HTML"
        path: str = "report.html"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        report = ctx.inputs[0]
        out_path = Path(cfg.path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(report, dict):
            table_rows_html = "".join(
                f"<tr><td style='padding:8px;border:1px solid #ddd'>{k}</td>"
                f"<td style='padding:8px;border:1px solid #ddd'>"
                f"{f'{v:.4f}' if isinstance(v, float) else str(v)}</td></tr>"
                for k, v in report.items()
            )
            html = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Athena Report</title>"
                "<style>body{font-family:sans-serif;padding:2rem}table{border-collapse:collapse;width:100%}</style>"
                "</head><body><h1>Pipeline Report</h1>"
                f"<table><tr><th>Metric</th><th>Value</th></tr>{table_rows_html}</table></body></html>"
            )
        else:
            html = f"<!DOCTYPE html><html><body><pre>{report}</pre></body></html>"

        if cfg.format == "PDF":
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                from matplotlib.backends.backend_pdf import PdfPages

                out_path = out_path.with_suffix(".pdf")
                save_dir = settings.data_dir / "reports"
                save_dir.mkdir(parents=True, exist_ok=True)
                final_path = save_dir / out_path.name if not out_path.is_absolute() else out_path

                with PdfPages(final_path) as pdf:
                    fig, ax = plt.subplots(figsize=(8.5, 11))
                    ax.axis("off")
                    if isinstance(report, dict):
                        table_data = [
                            [k, f"{v:.4f}" if isinstance(v, float) else str(v)]
                            for k, v in report.items()
                        ]
                        tbl = ax.table(
                            cellText=table_data,
                            colLabels=["Metric", "Value"],
                            loc="center",
                            cellLoc="left",
                        )
                        tbl.auto_set_font_size(False)
                        tbl.set_fontsize(10)
                        tbl.scale(1.2, 1.5)
                    else:
                        ax.text(
                            0.05, 0.95, str(report),
                            transform=ax.transAxes, va="top", fontsize=9,
                            family="monospace", wrap=True,
                        )
                    ax.set_title("Athena Pipeline Report", pad=20, fontsize=14)
                    pdf.savefig(fig, bbox_inches="tight")
                    plt.close(fig)

                ctx.logger.info("PDF report generated", path=str(final_path))
                return HandlerResult(
                    outputs=[],
                    preview=TextPreview(text=f"PDF report saved → {final_path}"),
                )
            except Exception as exc:
                ctx.logger.warning(f"PDF generation failed ({exc}), falling back to HTML")
                out_path = out_path.with_suffix(".html")
                out_path.write_text(html, encoding="utf-8")

        elif cfg.format == "Jupyter":
            try:
                import nbformat  # type: ignore[import-untyped]

                out_path = out_path.with_suffix(".ipynb")
                save_dir = settings.data_dir / "reports"
                save_dir.mkdir(parents=True, exist_ok=True)
                final_path = save_dir / out_path.name if not out_path.is_absolute() else out_path

                nb = nbformat.v4.new_notebook()
                cells = [nbformat.v4.new_markdown_cell("# Athena Pipeline Report")]
                if isinstance(report, dict):
                    md_rows = "\n".join(
                        f"| {k} | {f'{v:.4f}' if isinstance(v, float) else v} |"
                        for k, v in report.items()
                    )
                    cells.append(nbformat.v4.new_markdown_cell(
                        f"| Metric | Value |\n|---|---|\n{md_rows}"
                    ))
                else:
                    cells.append(nbformat.v4.new_code_cell(str(report)))
                nb.cells = cells

                with open(final_path, "w", encoding="utf-8") as f:
                    nbformat.write(nb, f)

                ctx.logger.info("Jupyter report generated", path=str(final_path))
                return HandlerResult(
                    outputs=[],
                    preview=TextPreview(text=f"Jupyter notebook saved → {final_path}"),
                )
            except ImportError:
                ctx.logger.warning("nbformat not installed, falling back to HTML")
                out_path = out_path.with_suffix(".html")
                out_path.write_text(html, encoding="utf-8")
        else:
            out_path.write_text(html, encoding="utf-8")

        encoded = base64.b64encode(html.encode("utf-8")).decode()
        ctx.logger.info("Report generated", path=str(out_path))
        return HandlerResult(
            outputs=[],
            preview=TextPreview(
                text=f"Report saved → {out_path}",
                download_filename=out_path.name,
                download_content=encoded,
            ),
        )


@node(
    "transformer_save", label="Transformer Save", category="deploy",
    description="Serialize a fitted scaler or encoder to disk for reuse",
    inputs=[Port("transformer", "transformer"), Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("Save Path (inside ~/.athena/transformers/)"),
    },
    code=EXPORT["transformer_save"],
)
class TransformerSaveHandler:
    class Config(BaseModel):
        path: str = "transformer.pkl"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        transformer = ctx.inputs[0]
        df: pd.DataFrame = ctx.inputs[1]

        save_dir = settings.data_dir / "transformers"
        save_dir.mkdir(parents=True, exist_ok=True)
        out_path = save_dir / cfg.path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "wb") as fh:
            pickle.dump(transformer, fh)

        ctx.logger.info("Transformer saved", path=str(out_path), type=type(transformer).__name__)
        return HandlerResult(
            outputs=[df],
            preview=TextPreview(
                text=f"Transformer saved → {out_path}\nType: {type(transformer).__name__}"
            ),
            metrics={"rows": float(len(df)), "cols": float(len(df.columns))},
        )


@node(
    "transformer_load", label="Transformer Load", category="deploy",
    description="Load a saved transformer and apply it to a dataset",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "path": ui("Load Path (inside ~/.athena/transformers/)"),
        "cols": ui("Columns to Transform (comma-sep, blank = auto)"),
    },
    code=EXPORT["transformer_load"],
)
class TransformerLoadHandler:
    class Config(BaseModel):
        path: str = "transformer.pkl"
        cols: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import numpy as np
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()

        load_path = settings.data_dir / "transformers" / cfg.path
        if not load_path.exists():
            raise FileNotFoundError(f"Transformer not found: {load_path}")

        with open(load_path, "rb") as fh:
            transformer = pickle.load(fh)

        user_cols = [c.strip() for c in cfg.cols.split(",") if c.strip()]

        try:
            if isinstance(transformer, dict):
                # Dict of {col: LabelEncoder} saved by label_enc node
                target_cols = user_cols if user_cols else list(transformer.keys())
                for col in target_cols:
                    if col in transformer and col in df.columns:
                        df[col] = transformer[col].transform(df[col].astype(str))
                applied = [c for c in target_cols if c in transformer and c in df.columns]
            else:
                if user_cols:
                    cols_present = [c for c in user_cols if c in df.columns]
                    missing = [c for c in user_cols if c not in df.columns]
                    if missing:
                        ctx.logger.warning("Columns not found in dataset", missing=missing)
                    if not cols_present:
                        raise ValueError(
                            f"None of the specified columns found in dataset. "
                            f"Available: {list(df.columns)}"
                        )
                else:
                    feature_names_in = getattr(transformer, "feature_names_in_", None)
                    if feature_names_in is not None:
                        cols_present = [c for c in feature_names_in if c in df.columns]
                    else:
                        cols_present = df.select_dtypes(include="number").columns.tolist()

                if cols_present:
                    n_expected = getattr(transformer, "n_features_in_", None)
                    if n_expected is not None and len(cols_present) != n_expected:
                        raise ValueError(
                            f"Transformer expects {n_expected} column(s) but {len(cols_present)} "
                            f"were provided ({cols_present}). Check that you specified the correct "
                            f"columns and loaded the correct transformer file."
                        )
                    # Pass numpy array to bypass sklearn's feature-name validation — the user
                    # explicitly chose which columns to transform, so we honour that choice.
                    transformed = transformer.transform(df[cols_present].to_numpy())
                    if hasattr(transformed, "toarray"):
                        transformed = transformed.toarray()
                    if transformed.shape[1] == len(cols_present):
                        # Same column count (scaler, label enc, etc.) — update in place
                        # so the rest of the dataset and column order are preserved.
                        # Assign column-by-column to avoid pandas CoW no-op on slices.
                        for i, col in enumerate(cols_present):
                            df[col] = transformed[:, i]
                    else:
                        # Column count changed (OHE expansion) — replace originals with new columns.
                        new_cols = (
                            list(transformer.get_feature_names_out())
                            if hasattr(transformer, "get_feature_names_out")
                            else [f"feat_{i}" for i in range(transformed.shape[1])]
                        )
                        trans_df = pd.DataFrame(transformed, columns=new_cols, index=df.index)
                        df = pd.concat([df.drop(columns=cols_present), trans_df], axis=1)
                applied = cols_present
        except Exception as exc:
            raise ValueError(f"Failed to apply transformer: {exc}") from exc

        ctx.logger.info(
            "Transformer loaded and applied",
            path=str(load_path), type=type(transformer).__name__, cols=applied,
        )
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df)), "cols_transformed": float(len(applied))},
        )


@node(
    "model_loader", label="Model Loader", category="deploy",
    description="Load a saved model from disk and run predictions on the connected dataset",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("predictions", "predictions")],
    fields={
        "path": ui("Model File Path"),
        "output_col": ui("Output Column Name"),
        "proba": ui("Return Probabilities"),
    },
    code=EXPORT["model_loader"],
)
class ModelLoaderHandler:
    class Config(BaseModel):
        path: str = "model.pkl"
        output_col: str = "y_pred"
        proba: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()

        load_path = Path(cfg.path)
        if not load_path.exists():
            raise FileNotFoundError(f"Model file not found: {load_path}")

        try:
            with open(load_path, "rb") as fh:
                model = pickle.load(fh)
        except Exception:
            model = joblib.load(load_path)

        ctx.logger.info("Model loaded, running predictions", path=str(load_path), type=type(model).__name__, rows=len(df))

        if cfg.proba and hasattr(model, "predict_proba"):
            proba = model.predict_proba(df)
            classes = getattr(model, "classes_", range(proba.shape[1]))
            for i, cls in enumerate(classes):
                df[f"{cfg.output_col}_proba_{cls}"] = proba[:, i]
        else:
            df[cfg.output_col] = model.predict(df)

        ctx.logger.info("Predictions done", rows=len(df))
        return HandlerResult(
            outputs=[df],
            preview=preview_dataframe(df),
            metrics={"rows": float(len(df))},
        )


@node(
    "pred_print", label="Prediction Printer", category="deploy",
    description="Display prediction values from a Prediction Node — shows each record's predicted value in the preview tab",
    inputs=[Port("predictions", "predictions")],
    fields={
        "pred_col": ui("Prediction Column Name"),
        "show_input": ui("Show Input Features Too"),
    },
    code=EXPORT["pred_print"],
)
class PredPrintHandler:
    class Config(BaseModel):
        pred_col: str = "y_pred"
        show_input: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]

        pred_col_base = cfg.pred_col.strip() or "y_pred"
        pred_cols = [c for c in df.columns if c == pred_col_base or c.startswith(f"{pred_col_base}_proba_")]
        if not pred_cols:
            avail = ", ".join(df.columns.tolist())
            raise ValueError(
                f"Prediction column '{pred_col_base}' not found. Available columns: {avail}"
            )

        display_df = df if cfg.show_input else df[pred_cols]

        # Cap preview at 200 rows — more than enough for manual inspection
        preview_df = display_df.head(200)
        safe_rows = []
        for row in preview_df.values.tolist():
            safe_rows.append([
                round(v, 6) if isinstance(v, float) else v for v in row
            ])

        preview = DataframePreview(
            columns=list(preview_df.columns),
            rows=safe_rows,
            shape=(len(display_df), len(display_df.columns)),
        )

        ctx.logger.info("Predictions printed", records=len(df), pred_cols=pred_cols)
        return HandlerResult(
            outputs=[],
            preview=preview,
            metrics={"records": float(len(df))},
        )


@node(
    "api_gen", label="API Generator", category="deploy",
    description="Expose model as REST API endpoint",
    inputs=[Port("model", "model")],
    outputs=[Port("endpoint", "endpoint")],
    fields={
        "host": ui(widget="text"),
        "port": ui(widget="number"),
        "framework": ui(widget="select", options=["FastAPI", "Flask"]),
    },
    export_note="Not implemented yet.",
    available=False, unavailable_reason="Not implemented yet: model serving via BentoML is roadmap phase 2.",
)
class ApiGenHandler:
    class Config(BaseModel):
        host: str = '0.0.0.0'
        port: int = 8000
        framework: str = 'FastAPI'

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        raise NotImplementedError("Not implemented yet: model serving via BentoML is roadmap phase 2.")

