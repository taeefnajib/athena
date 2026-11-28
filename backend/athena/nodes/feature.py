from pydantic import BaseModel
from typing import Literal
import pandas as pd
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler, MaxAbsScaler, LabelEncoder
from sklearn.preprocessing import OneHotEncoder

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.utils.dataframes import preview_dataframe




@node(
    "scaler", label="Scaler", category="feature",
    description="Normalize or standardize features",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset"), Port("transformer", "transformer")],
    fields={
        "method": ui(),
        "cols": ui("Columns"),
    },
    code=EXPORT["scaler"],
)
class ScalerHandler:
    class Config(BaseModel):
        method: Literal["StandardScaler", "MinMaxScaler", "RobustScaler", "MaxAbsScaler"] = "StandardScaler"
        cols: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        scaler_map = {
            "StandardScaler": StandardScaler,
            "MinMaxScaler": MinMaxScaler,
            "RobustScaler": RobustScaler,
            "MaxAbsScaler": MaxAbsScaler,
        }
        scaler = scaler_map[cfg.method]()

        num_cols = df.select_dtypes(include="number").columns.tolist()
        if "target" in num_cols:
            num_cols.remove("target")

        target_cols = [c.strip() for c in cfg.cols.split(",") if c.strip() and c.strip() in df.columns] if cfg.cols.strip() else num_cols

        if target_cols:
            df[target_cols] = scaler.fit_transform(df[target_cols])

        ctx.logger.info("Scaled", method=cfg.method, cols=len(target_cols))
        return HandlerResult(outputs=[df, scaler], preview=preview_dataframe(df),
                             replay={"kind": "columns_transform", "transformer": scaler, "cols": target_cols} if target_cols else {"kind": "skip"})


@node(
    "ohe", label="One-Hot Encoder", category="feature",
    description="Encode categorical columns as binary",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset"), Port("transformer", "transformer")],
    fields={
        "cols": ui("Columns"),
        "drop": ui("Drop First"),
        "sparse": ui("Sparse Output"),
    },
    code=EXPORT["ohe"],
)
class OheHandler:
    class Config(BaseModel):
        cols: str = ""
        drop: bool = False
        sparse: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        cat_cols = [c.strip() for c in cfg.cols.split(",") if c.strip() and c.strip() in df.columns]
        if not cat_cols:
            cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

        if not cat_cols:
            ctx.logger.info("OHE: no categorical columns found, passthrough")
            return HandlerResult(outputs=[df, None], preview=preview_dataframe(df), replay={"kind": "skip"})

        drop_opt = "first" if cfg.drop else None
        enc = OneHotEncoder(drop=drop_opt, sparse_output=False, handle_unknown="ignore")
        encoded = enc.fit_transform(df[cat_cols])
        feature_names = enc.get_feature_names_out(cat_cols)
        enc_df = pd.DataFrame(encoded, columns=feature_names, index=df.index)
        result = pd.concat([df.drop(columns=cat_cols), enc_df], axis=1)

        ctx.logger.info("OHE", cols=cat_cols, new_features=len(feature_names))
        return HandlerResult(outputs=[result, enc], preview=preview_dataframe(result),
                             replay={"kind": "one_hot", "encoder": enc, "cols": cat_cols})


@node(
    "label_enc", label="Label Encoder", category="feature",
    description="Encode labels as integers",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset"), Port("transformer", "transformer")],
    fields={
        "cols": ui("Columns"),
    },
    code=EXPORT["label_enc"],
)
class LabelEncHandler:
    class Config(BaseModel):
        cols: str = "target"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        cols = [c.strip() for c in cfg.cols.split(",") if c.strip() and c.strip() in df.columns]
        encoders: dict[str, LabelEncoder] = {}
        for col in cols:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            encoders[col] = le
        ctx.logger.info("Label encoded", cols=cols)
        return HandlerResult(outputs=[df, encoders], preview=preview_dataframe(df),
                             replay={"kind": "label_encode", "classes": {c: [str(x) for x in le.classes_] for c, le in encoders.items()}})


@node(
    "str_split", label="String Splitter", category="feature",
    description="Split a string column by a configurable separator",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "col": ui("Column"),
        "sep": ui("Separator"),
        "expand": ui("Expand to Columns"),
        "prefix": ui("Column Prefix"),
    },
    code=EXPORT["str_split"],
)
class StrSplitHandler:
    class Config(BaseModel):
        col: str = "text"
        sep: Literal["space", "tab", "comma", "hyphen", "pipe", "semicolon"] = "space"
        expand: bool = True
        prefix: str = "part"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()

        sep_map = {"space": " ", "tab": "\t", "comma": ",", "hyphen": "-", "pipe": "|", "semicolon": ";"}
        sep = sep_map[cfg.sep]

        if cfg.col not in df.columns:
            raise ValueError(f"Column '{cfg.col}' not found in dataset")

        split_result = df[cfg.col].str.split(sep, expand=cfg.expand)

        if cfg.expand:
            split_result.columns = [f"{cfg.prefix}_{i}" for i in range(len(split_result.columns))]
            df = pd.concat([df, split_result], axis=1)
        else:
            df[f"{cfg.col}_split"] = split_result

        ctx.logger.info("String split", col=cfg.col, sep=cfg.sep, new_cols=len(split_result.columns) if cfg.expand else 1)
        return HandlerResult(outputs=[df], preview=preview_dataframe(df))


@node(
    "col_selector", label="Column Selector", category="feature",
    description="Select or drop columns",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "mode": ui(),
        "cols": ui("Columns"),
    },
    code=EXPORT["col_selector"],
)
class ColSelectorHandler:
    class Config(BaseModel):
        mode: Literal["include", "exclude"] = "include"
        cols: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        cols = [c.strip() for c in cfg.cols.split(",") if c.strip()]
        if not cols:
            raise ValueError("No columns specified — provide at least one column name")
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"Columns not found in dataset: {missing}")
        result = df[cols] if cfg.mode == "include" else df.drop(columns=cols)
        ctx.logger.info("Column selector", mode=cfg.mode, cols=cols, remaining=len(result.columns))
        return HandlerResult(outputs=[result], preview=preview_dataframe(result), replay={"kind": "select", "mode": cfg.mode, "cols": cols})


@node(
    "feat_gen", label="Feature Generator", category="feature",
    description="Create polynomial or interaction features",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "degree": ui(),
        "interaction": ui("Interaction Only"),
    },
    code=EXPORT["feat_gen"],
)
class FeatGenHandler:
    class Config(BaseModel):
        degree: int = 2
        interaction: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.preprocessing import PolynomialFeatures
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        num_cols = df.select_dtypes(include="number").columns.tolist()
        # Don't transform the target column
        from athena.utils.dataframes import get_target_column
        try:
            target = get_target_column(df)
            if target in num_cols:
                num_cols.remove(target)
        except Exception:
            pass
        poly = PolynomialFeatures(degree=cfg.degree, interaction_only=cfg.interaction, include_bias=False)
        X_poly = poly.fit_transform(df[num_cols])
        new_names = poly.get_feature_names_out(num_cols)
        poly_df = pd.DataFrame(X_poly, columns=new_names, index=df.index)
        # Drop original numeric cols, add polynomial features
        result = pd.concat([df.drop(columns=num_cols), poly_df], axis=1)
        ctx.logger.info("Feature generation", degree=cfg.degree, features_in=len(num_cols), features_out=len(new_names))
        return HandlerResult(outputs=[result], preview=preview_dataframe(result),
                             metrics={"features_in": float(len(num_cols)), "features_out": float(len(new_names))},
                             replay={"kind": "poly", "transformer": poly, "cols": num_cols})


@node(
    "tfidf", label="Text Vectorizer", category="feature",
    description="TF-IDF or CountVectorizer for text",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "col": ui("Text Column"),
        "method": ui(),
        "max_features": ui("Max Features"),
    },
    code=EXPORT["tfidf"],
)
class TfidfHandler:
    class Config(BaseModel):
        col: str = "text"
        method: Literal["TF-IDF", "CountVectorizer"] = "TF-IDF"
        max_features: int = 1000

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
        import scipy.sparse
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        if cfg.col not in df.columns:
            raise ValueError(f"Column '{cfg.col}' not found in dataset")
        text_series = df[cfg.col].fillna("").astype(str)
        vec_cls = TfidfVectorizer if cfg.method == "TF-IDF" else CountVectorizer
        vec = vec_cls(max_features=cfg.max_features)
        mat = vec.fit_transform(text_series)
        feat_names = [f"{cfg.col}_{name}" for name in vec.get_feature_names_out()]
        feat_df = pd.DataFrame(mat.toarray(), columns=feat_names, index=df.index)
        result = pd.concat([df.drop(columns=[cfg.col]), feat_df], axis=1)
        ctx.logger.info("Text vectorized", method=cfg.method, features=mat.shape[1])
        return HandlerResult(outputs=[result], preview=preview_dataframe(result),
                             metrics={"features": float(mat.shape[1])}, replay={"kind": "text", "vectorizer": vec, "col": cfg.col})


@node(
    "date_feat", label="Date Feature Extractor", category="feature",
    description="Extract year, month, day, weekday, etc.",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "col": ui("Date Column"),
        "features": ui("Extract"),
    },
    code=EXPORT["date_feat"],
)
class DateFeatHandler:
    class Config(BaseModel):
        col: str = "date"
        features: str = "year,month,day,weekday"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        if cfg.col not in df.columns:
            raise ValueError(f"Column '{cfg.col}' not found in dataset")
        dt = pd.to_datetime(df[cfg.col], errors="coerce")
        extractors = {
            "year": dt.dt.year, "month": dt.dt.month, "day": dt.dt.day,
            "weekday": dt.dt.weekday, "hour": dt.dt.hour, "minute": dt.dt.minute,
            "quarter": dt.dt.quarter, "week": dt.dt.isocalendar().week.astype(int),
            "dayofyear": dt.dt.dayofyear, "is_weekend": (dt.dt.weekday >= 5).astype(int),
        }
        requested = [f.strip() for f in cfg.features.split(",") if f.strip()]
        added = 0
        for feat in requested:
            if feat in extractors:
                df[f"{cfg.col}_{feat}"] = extractors[feat]
                added += 1
        ctx.logger.info("Date features extracted", col=cfg.col, added=added)
        return HandlerResult(outputs=[df], preview=preview_dataframe(df),
                             metrics={"features_added": float(added)}, replay={"kind": "dates", "col": cfg.col, "features": requested})


@node(
    "feat_imp_sel", label="Feature Importance Sel", category="feature",
    description="Select top features by importance score",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "k": ui("Top K Features"),
        "method": ui(),
    },
    code=EXPORT["feat_imp_sel"],
)
class FeatImpSelHandler:
    class Config(BaseModel):
        k: int = 20
        method: Literal["chi2", "f_classif", "mutual_info"] = "f_classif"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.feature_selection import SelectKBest, chi2, f_classif, mutual_info_classif
        from athena.utils.dataframes import get_target_column
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0]
        target_col = get_target_column(df)
        X = df.drop(columns=[target_col])
        y = df[target_col]
        num_X = X.select_dtypes(include="number")
        score_fn = {"chi2": chi2, "f_classif": f_classif, "mutual_info": mutual_info_classif}[cfg.method]
        k = min(cfg.k, len(num_X.columns))
        selector = SelectKBest(score_fn, k=k)
        selector.fit(num_X.fillna(0), y)
        selected = num_X.columns[selector.get_support()].tolist()
        # Keep non-numeric cols + selected numeric + target
        non_num = [c for c in X.columns if c not in num_X.columns]
        result = df[non_num + selected + [target_col]]
        ctx.logger.info("Feature selection", method=cfg.method, k=k, selected=len(selected))
        return HandlerResult(outputs=[result], preview=preview_dataframe(result),
                             metrics={"features_in": float(len(num_X.columns)), "features_out": float(len(selected))})


@node(
    "pca", label="PCA", category="feature",
    description="Principal Component Analysis",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "n_components": ui("Components"),
        "whiten": ui(),
    },
    code=EXPORT["pca"],
)
class PcaHandler:
    class Config(BaseModel):
        n_components: int = 10
        whiten: bool = False

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        from sklearn.decomposition import PCA
        from athena.utils.dataframes import get_target_column
        cfg = self.Config(**ctx.config)
        df: pd.DataFrame = ctx.inputs[0].copy()
        try:
            target_col = get_target_column(df)
            y = df[target_col]
            X = df.drop(columns=[target_col])
            has_target = True
        except Exception:
            X = df
            has_target = False
        num_X = X.select_dtypes(include="number")
        n = min(cfg.n_components, len(num_X.columns), len(df))
        pca = PCA(n_components=n, whiten=cfg.whiten)
        comps = pca.fit_transform(num_X.fillna(0))
        comp_df = pd.DataFrame(comps, columns=[f"pc_{i+1}" for i in range(n)], index=df.index)
        non_num = [c for c in X.columns if c not in num_X.columns]
        result = pd.concat([df[non_num], comp_df], axis=1)
        if has_target:
            result[target_col] = y.values
        var_explained = float(pca.explained_variance_ratio_.sum())
        ctx.logger.info("PCA", components=n, variance_explained=var_explained)
        return HandlerResult(outputs=[result], preview=preview_dataframe(result),
                             metrics={"components": float(n), "variance_explained": var_explained},
                             replay={"kind": "pca", "pca": pca, "cols": list(num_X.columns), "target": target_col if has_target else None})


@node(
    "embedding", label="Embedding Generator", category="feature",
    description="Generate embeddings for text or categories",
    inputs=[Port("dataset", "dataset")],
    outputs=[Port("dataset", "dataset")],
    fields={
        "col": ui("Column", widget="text"),
        "dim": ui("Dimensions", widget="number"),
    },
    export_note="Not implemented yet.",
    available=False, unavailable_reason="Not implemented yet: embeddings arrive with the deep learning plugins (roadmap phase 3).",
)
class EmbeddingHandler:
    class Config(BaseModel):
        col: str = 'text'
        dim: int = 128

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        raise NotImplementedError("Not implemented yet: embeddings arrive with the deep learning plugins (roadmap phase 3).")

