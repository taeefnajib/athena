from pydantic import BaseModel
from typing import Literal
import pandas as pd
import numpy as np

from athena.core.registry import register
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.plotting import fig_to_plot_preview
from athena.schemas.artifacts import MetricsPreview, TextPreview, DataframeInfoPreview, ColumnInfo


@register("metrics")
class MetricsHandler:
    class Config(BaseModel):
        task: Literal["classification", "regression"] = "classification"
        average: Literal["micro", "macro", "weighted"] = "weighted"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        X_test: pd.DataFrame = ctx.inputs[1]
        y_test: pd.Series = ctx.inputs[2]

        y_pred = model.predict(X_test)
        ctx.logger.info("Computing metrics", task=cfg.task, samples=len(y_test))

        result_metrics: dict[str, float] = {}

        if cfg.task == "classification":
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
            result_metrics["accuracy"] = float(accuracy_score(y_test, y_pred))
            result_metrics["precision"] = float(precision_score(y_test, y_pred, average=cfg.average, zero_division=0))
            result_metrics["recall"] = float(recall_score(y_test, y_pred, average=cfg.average, zero_division=0))
            result_metrics["f1"] = float(f1_score(y_test, y_pred, average=cfg.average, zero_division=0))
            try:
                from sklearn.metrics import roc_auc_score
                if hasattr(model, "predict_proba"):
                    proba = model.predict_proba(X_test)
                    if proba.shape[1] == 2:
                        result_metrics["roc_auc"] = float(roc_auc_score(y_test, proba[:, 1]))
                    else:
                        result_metrics["roc_auc"] = float(roc_auc_score(y_test, proba, multi_class="ovr"))
            except Exception:
                pass
        else:
            from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
            result_metrics["rmse"] = float(np.sqrt(mean_squared_error(y_test, y_pred)))
            result_metrics["mae"] = float(mean_absolute_error(y_test, y_pred))
            result_metrics["r2"] = float(r2_score(y_test, y_pred))

        ctx.logger.info("Metrics computed", **result_metrics)
        return HandlerResult(
            outputs=[result_metrics],
            preview=MetricsPreview(values=result_metrics),
            metrics=result_metrics,
        )


@register("conf_matrix")
class ConfMatrixHandler:
    class Config(BaseModel):
        normalize: Literal["true", "pred", "all", "none"] = "none"
        cmap: str = "Blues"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        X_test: pd.DataFrame = ctx.inputs[1]
        y_test: pd.Series = ctx.inputs[2]
        y_pred = model.predict(X_test)

        from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
        import matplotlib.pyplot as plt

        norm = None if cfg.normalize == "none" else cfg.normalize
        cm = confusion_matrix(y_test, y_pred, normalize=norm)

        fig, ax = plt.subplots(figsize=(6, 5))
        disp = ConfusionMatrixDisplay(confusion_matrix=cm)
        disp.plot(ax=ax, cmap=cfg.cmap, colorbar=False)
        ax.set_title("Confusion Matrix")
        fig.tight_layout()

        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Confusion matrix plotted")
        return HandlerResult(outputs=[preview], preview=preview)


@register("residual")
class ResidualHandler:
    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        model = ctx.inputs[0]
        X_test: pd.DataFrame = ctx.inputs[1]
        y_test: pd.Series = ctx.inputs[2]
        y_pred = model.predict(X_test)

        import matplotlib.pyplot as plt

        residuals = np.array(y_test) - np.array(y_pred)
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        axes[0].scatter(y_pred, residuals, alpha=0.5, s=20)
        axes[0].axhline(0, color="red", linestyle="--", linewidth=1)
        axes[0].set_xlabel("Predicted")
        axes[0].set_ylabel("Residual")
        axes[0].set_title("Residuals vs Predicted")

        axes[1].hist(residuals, bins=30, edgecolor="white", linewidth=0.5)
        axes[1].set_xlabel("Residual")
        axes[1].set_title("Residual Distribution")

        fig.tight_layout()
        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Residual plot created")
        return HandlerResult(outputs=[preview], preview=preview)


@register("roc_curve")
class RocCurveHandler:
    class Config(BaseModel):
        multi_class: Literal["ovr", "ovo"] = "ovr"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        X_test: pd.DataFrame = ctx.inputs[1]
        y_test: pd.Series = ctx.inputs[2]

        if not hasattr(model, "predict_proba"):
            raise ValueError(f"{type(model).__name__} does not support predict_proba — cannot plot ROC curve")

        from sklearn.metrics import roc_curve, auc
        from sklearn.preprocessing import label_binarize
        import matplotlib.pyplot as plt

        classes = np.unique(y_test)
        proba = model.predict_proba(X_test)

        fig, ax = plt.subplots(figsize=(6, 5))

        if len(classes) == 2:
            fpr, tpr, _ = roc_curve(y_test, proba[:, 1])
            roc_auc = auc(fpr, tpr)
            ax.plot(fpr, tpr, lw=2, label=f"AUC = {roc_auc:.3f}")
        else:
            y_bin = label_binarize(y_test, classes=classes)
            for i, cls in enumerate(classes):
                fpr, tpr, _ = roc_curve(y_bin[:, i], proba[:, i])
                roc_auc = auc(fpr, tpr)
                ax.plot(fpr, tpr, lw=1.5, label=f"Class {cls} (AUC={roc_auc:.2f})")

        ax.plot([0, 1], [0, 1], "k--", lw=1)
        ax.set_xlabel("False Positive Rate")
        ax.set_ylabel("True Positive Rate")
        ax.set_title("ROC Curve")
        ax.legend(loc="lower right", fontsize=9)
        fig.tight_layout()

        preview = fig_to_plot_preview(fig)
        ctx.logger.info("ROC curve plotted", classes=len(classes))
        return HandlerResult(outputs=[preview], preview=preview)


@register("feat_imp_viz")
class FeatImpVizHandler:
    class Config(BaseModel):
        top_n: int = 20

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        model = ctx.inputs[0]
        import matplotlib.pyplot as plt

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
            feature_names = getattr(model, "feature_names_in_", [f"f{i}" for i in range(len(importances))])
        elif hasattr(model, "coef_"):
            coef = np.abs(model.coef_)
            importances = coef.mean(axis=0) if coef.ndim > 1 else coef
            feature_names = getattr(model, "feature_names_in_", [f"f{i}" for i in range(len(importances))])
        else:
            raise ValueError(f"{type(model).__name__} does not expose feature importances")

        idx = np.argsort(importances)[-cfg.top_n:]
        fig, ax = plt.subplots(figsize=(7, max(4, len(idx) * 0.3)))
        ax.barh(range(len(idx)), importances[idx])
        ax.set_yticks(range(len(idx)))
        ax.set_yticklabels([feature_names[i] for i in idx], fontsize=8)
        ax.set_xlabel("Importance")
        ax.set_title(f"Top {len(idx)} Feature Importances")
        fig.tight_layout()

        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Feature importance plot created", features=len(idx))
        return HandlerResult(outputs=[preview], preview=preview)


@register("df_info")
class DfInfoHandler:
    class Config(BaseModel):
        max_unique: int = 10

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]

        duplicates = int(df.duplicated().sum())
        total_missing = int(df.isnull().sum().sum())
        missing_pct = df.isnull().mean().mean() * 100

        col_infos: list[ColumnInfo] = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            n_missing = int(df[col].isnull().sum())
            col_missing_pct = n_missing / len(df) * 100 if len(df) > 0 else 0.0
            n_unique = int(df[col].nunique(dropna=True))

            if pd.api.types.is_numeric_dtype(df[col]):
                s = df[col].dropna()
                if len(s) > 0:
                    col_infos.append(ColumnInfo(
                        name=col, dtype=dtype,
                        missing=n_missing, missing_pct=round(col_missing_pct, 2),
                        unique=n_unique,
                        min=float(s.min()), max=float(s.max()),
                        mean=float(s.mean()), median=float(s.median()),
                        std=float(s.std()) if len(s) > 1 else 0.0,
                    ))
                else:
                    col_infos.append(ColumnInfo(
                        name=col, dtype=dtype,
                        missing=n_missing, missing_pct=round(col_missing_pct, 2),
                        unique=n_unique,
                    ))
            else:
                top_vals = [str(v) for v in df[col].value_counts(dropna=True).head(cfg.max_unique).index.tolist()]
                col_infos.append(ColumnInfo(
                    name=col, dtype=dtype,
                    missing=n_missing, missing_pct=round(col_missing_pct, 2),
                    unique=n_unique, top_values=top_vals,
                ))

        ctx.logger.info("DataFrame info", rows=df.shape[0], cols=df.shape[1])
        return HandlerResult(
            outputs=[df],
            preview=DataframeInfoPreview(
                shape=(df.shape[0], df.shape[1]),
                duplicates=duplicates,
                total_missing=total_missing,
                missing_pct=round(missing_pct, 2),
                info_columns=col_infos,
            ),
            metrics={"rows": float(df.shape[0]), "cols": float(df.shape[1]), "missing_cells": float(total_missing)},
        )


@register("data_viz")
class DataVizHandler:
    class Config(BaseModel):
        chart_type: Literal["Histogram", "Bar", "Line", "Scatter", "Pie", "Box", "Violin", "Heatmap"] = "Histogram"
        x_col: str = ""
        y_col: str = ""
        col: str = ""
        hue: str = ""
        bins: int = 30
        title: str = ""
        palette: str = "viridis"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        chart_title = cfg.title if cfg.title else f"{cfg.chart_type} Chart"

        try:
            import seaborn as sns
            has_sns = True
        except ImportError:
            has_sns = False

        hue_col = cfg.hue.strip() if cfg.hue.strip() and cfg.hue.strip() in df.columns else None
        num_cols = df.select_dtypes(include="number").columns.tolist()

        fig, ax = plt.subplots(figsize=(8, 5))

        if cfg.chart_type == "Histogram":
            col = (cfg.col or cfg.x_col).strip()
            if not col or col not in df.columns:
                col = num_cols[0] if num_cols else df.columns[0]
            if has_sns:
                sns.histplot(data=df, x=col, bins=cfg.bins, ax=ax, hue=hue_col)
            else:
                ax.hist(df[col].dropna(), bins=cfg.bins)
            ax.set_xlabel(col)

        elif cfg.chart_type == "Bar":
            x = cfg.x_col.strip()
            y = cfg.y_col.strip()
            if not x or x not in df.columns:
                x = df.columns[0]
            if has_sns and y and y in df.columns:
                sns.barplot(data=df, x=x, y=y, ax=ax, hue=hue_col)
                ax.set_ylabel(y)
            elif y and y in df.columns:
                grp = df.groupby(x)[y].mean()
                ax.bar(grp.index.astype(str), grp.values)
                ax.set_ylabel(y)
            else:
                vc = df[x].value_counts().head(20)
                ax.bar(vc.index.astype(str), vc.values)
                ax.set_ylabel("Count")
            ax.set_xlabel(x)
            plt.xticks(rotation=45, ha="right")

        elif cfg.chart_type == "Line":
            x = cfg.x_col.strip()
            y = cfg.y_col.strip()
            if not x or x not in df.columns:
                x = df.columns[0]
            if not y or y not in df.columns:
                y = num_cols[0] if num_cols else df.columns[0]
            if has_sns:
                sns.lineplot(data=df, x=x, y=y, ax=ax, hue=hue_col)
            else:
                ax.plot(df[x], df[y])
            ax.set_xlabel(x)
            ax.set_ylabel(y)

        elif cfg.chart_type == "Scatter":
            x = cfg.x_col.strip()
            y = cfg.y_col.strip()
            if not x or x not in df.columns:
                x = num_cols[0] if len(num_cols) > 0 else df.columns[0]
            if not y or y not in df.columns:
                y = num_cols[1] if len(num_cols) > 1 else df.columns[0]
            if has_sns:
                sns.scatterplot(data=df, x=x, y=y, ax=ax, hue=hue_col, alpha=0.6)
            else:
                ax.scatter(df[x], df[y], alpha=0.5, s=20)
            ax.set_xlabel(x)
            ax.set_ylabel(y)

        elif cfg.chart_type == "Pie":
            col = (cfg.col or cfg.x_col).strip()
            if not col or col not in df.columns:
                col = df.columns[0]
            vc = df[col].value_counts().head(10)
            try:
                colors = sns.color_palette(cfg.palette, n_colors=len(vc)) if has_sns else None
            except Exception:
                colors = None
            ax.pie(vc.values, labels=vc.index.astype(str), autopct="%1.1f%%", colors=colors)
            ax.set_aspect("equal")

        elif cfg.chart_type == "Box":
            y = (cfg.y_col or cfg.col).strip()
            x = cfg.x_col.strip()
            if not y or y not in df.columns:
                y = num_cols[0] if num_cols else df.columns[0]
            x_arg = x if x and x in df.columns else None
            if has_sns:
                sns.boxplot(data=df, x=x_arg, y=y, ax=ax, hue=hue_col)
            else:
                if x_arg:
                    groups = [g.dropna().values for _, g in df.groupby(x_arg)[y]]
                    labels_list = [str(k) for k in df[x_arg].unique()]
                    ax.boxplot(groups, labels=labels_list)
                else:
                    ax.boxplot(df[y].dropna())
            ax.set_ylabel(y)

        elif cfg.chart_type == "Violin":
            y = (cfg.y_col or cfg.col).strip()
            x = cfg.x_col.strip()
            if not y or y not in df.columns:
                y = num_cols[0] if num_cols else df.columns[0]
            x_arg = x if x and x in df.columns else None
            if has_sns:
                sns.violinplot(data=df, x=x_arg, y=y, ax=ax, hue=hue_col)
            else:
                if x_arg:
                    groups = [g.dropna().values for _, g in df.groupby(x_arg)[y]]
                    labels_list = [str(k) for k in df[x_arg].unique()]
                    ax.boxplot(groups, labels=labels_list)
                else:
                    ax.boxplot(df[y].dropna())
            ax.set_ylabel(y)

        elif cfg.chart_type == "Heatmap":
            top_n = min(20, len(num_cols))
            corr = df[num_cols[:top_n]].corr()
            if has_sns:
                plt.close(fig)
                fig, ax = plt.subplots(figsize=(max(6, top_n * 0.5), max(5, top_n * 0.45)))
                sns.heatmap(corr, annot=top_n <= 15, fmt=".2f", ax=ax, cmap=cfg.palette)
            else:
                im = ax.imshow(corr.values, aspect="auto", cmap=cfg.palette, vmin=-1, vmax=1)
                fig.colorbar(im, ax=ax)
                ax.set_xticks(range(len(corr.columns)))
                ax.set_yticks(range(len(corr.columns)))
                ax.set_xticklabels(corr.columns, rotation=90, fontsize=8)
                ax.set_yticklabels(corr.columns, fontsize=8)

        ax.set_title(chart_title)
        fig.tight_layout()

        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Data viz", chart_type=cfg.chart_type)
        return HandlerResult(outputs=[preview], preview=preview)


@register("corr_check")
class CorrCheckHandler:
    class Config(BaseModel):
        mode: Literal["Matrix", "Pairwise"] = "Matrix"
        method: Literal["pearson", "spearman", "kendall"] = "pearson"
        col1: str = ""
        col2: str = ""
        top_n: int = 20
        cmap: str = "coolwarm"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        num_df = df.select_dtypes(include="number")

        if cfg.mode == "Pairwise":
            c1, c2 = cfg.col1.strip(), cfg.col2.strip()
            if not c1 or not c2:
                raise ValueError("Pairwise mode requires col1 and col2 to be set")
            if c1 not in df.columns or c2 not in df.columns:
                raise ValueError(f"Columns not found: {c1!r}, {c2!r}")

            fig, axes = plt.subplots(1, 2, figsize=(10, 4))
            axes[0].scatter(df[c1], df[c2], alpha=0.5, s=20)
            axes[0].set_xlabel(c1)
            axes[0].set_ylabel(c2)
            corr_val = float(df[c1].corr(df[c2], method=cfg.method))
            axes[0].set_title(f"{c1} vs {c2}\n{cfg.method} r = {corr_val:.3f}")

            try:
                valid = df[[c1, c2]].dropna()
                coefs = np.polyfit(valid[c1].values, valid[c2].values, 1)
                x_line = np.array([valid[c1].min(), valid[c1].max()])
                axes[0].plot(x_line, np.polyval(coefs, x_line), "r-", linewidth=1.5)
            except Exception:
                pass

            valid_pair = df[[c1, c2]].dropna()
            axes[1].hist2d(valid_pair[c1].values, valid_pair[c2].values, bins=20, cmap=cfg.cmap)
            axes[1].set_xlabel(c1)
            axes[1].set_ylabel(c2)
            axes[1].set_title("Joint Distribution")
        else:
            top_n = min(cfg.top_n, len(num_df.columns))
            corr = num_df.iloc[:, :top_n].corr(method=cfg.method)

            try:
                import seaborn as sns
                fig, ax = plt.subplots(figsize=(max(6, top_n * 0.5), max(5, top_n * 0.45)))
                sns.heatmap(corr, annot=top_n <= 15, fmt=".2f", ax=ax, cmap=cfg.cmap, center=0)
                ax.set_title(f"Correlation Matrix ({cfg.method.title()})")
            except ImportError:
                fig, ax = plt.subplots(figsize=(max(6, top_n * 0.5), max(5, top_n * 0.45)))
                im = ax.imshow(corr.values, aspect="auto", cmap=cfg.cmap, vmin=-1, vmax=1)
                fig.colorbar(im, ax=ax)
                ax.set_xticks(range(len(corr.columns)))
                ax.set_yticks(range(len(corr.columns)))
                ax.set_xticklabels(corr.columns, rotation=90, fontsize=8)
                ax.set_yticklabels(corr.columns, fontsize=8)
                ax.set_title(f"Correlation Matrix ({cfg.method.title()})")

        plt.tight_layout()
        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Correlation check", mode=cfg.mode, method=cfg.method)
        return HandlerResult(outputs=[preview], preview=preview)


@register("class_dist")
class ClassDistHandler:
    class Config(BaseModel):
        target_col: str = ""
        show_percent: bool = True
        palette: str = "Set2"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from athena.utils.dataframes import get_target_column

        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = cfg.target_col.strip() if cfg.target_col.strip() else get_target_column(df)

        if target_col not in df.columns:
            raise ValueError(f"Target column '{target_col}' not found in dataset")

        vc = df[target_col].value_counts()
        total = len(df)
        labels = vc.index.astype(str).tolist()
        counts = vc.values.astype(float)
        imbalance_ratio = float(counts.max() / counts.min()) if counts.min() > 0 else float("inf")

        try:
            import seaborn as sns
            colors = sns.color_palette(cfg.palette, n_colors=len(labels))
        except ImportError:
            colors = None

        fig, axes = plt.subplots(1, 2, figsize=(10, 4))

        bars = axes[0].bar(labels, counts, color=colors)
        axes[0].set_xlabel(target_col)
        axes[0].set_ylabel("Count")
        axes[0].set_title(f"Class Distribution — {target_col}")
        axes[0].tick_params(axis="x", rotation=45)

        if cfg.show_percent:
            for bar, count in zip(bars, counts):
                pct = count / total * 100
                axes[0].text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + total * 0.005,
                    f"{pct:.1f}%", ha="center", va="bottom", fontsize=9,
                )

        axes[1].pie(
            counts, labels=labels,
            autopct="%1.1f%%" if cfg.show_percent else None,
            colors=colors,
        )
        axes[1].set_title("Proportions")

        fig.tight_layout()

        preview = fig_to_plot_preview(fig)
        ctx.logger.info("Class distribution", target=target_col, classes=len(vc), imbalance_ratio=imbalance_ratio)
        return HandlerResult(
            outputs=[preview],
            preview=preview,
            metrics={"classes": float(len(vc)), "imbalance_ratio": imbalance_ratio},
        )
