"""Export templates: data input, quality, feature engineering, balancing and splits.
Each mirrors its node's handler, so the exported script computes what Athena computed."""
from __future__ import annotations

import json
from typing import Any

from athena.nodes.export.common import Template, items, lines

V = dict[str, Any]


# ---- data input ------------------------------------------------------------------------------------

def csv_loader(v: V) -> str:
    sep = str(v["sep"]).replace("\\t", "\t")
    return lines("import pandas as pd",
                 f"{v['out_dataset']} = pd.read_csv({v['path']!r}, sep={sep!r}, header={0 if v['header'] else None}, encoding={v['encoding']!r})")


def excel_loader(v: V) -> str:
    return lines("import pandas as pd",
                 f"{v['out_dataset']} = pd.read_excel({v['path']!r}, sheet_name={v['sheet']!r}, header={0 if v['header'] else None})")


def json_loader(v: V) -> str:
    return lines("import pandas as pd", f"{v['out_dataset']} = pd.read_json({v['path']!r}, orient={v['orient']!r})")


def parquet_loader(v: V) -> str:
    cols = f", columns={items(v['columns'])!r}" if items(v["columns"]) else ""
    head = f".head({int(v['limit'])})" if v["limit"] else ""
    return lines("import pandas as pd", f"{v['out_dataset']} = pd.read_parquet({v['path']!r}{cols}){head}")


def synth_data(v: V) -> str:
    out = v["out_dataset"]
    if v["task"] == "regression":
        make = f"make_regression(n_samples={v['rows']}, n_features={v['features']}, noise=0.1, random_state=42)"
        imp = "from sklearn.datasets import make_regression"
    else:
        inf = min(int(v["features"]), 5)
        make = (f"make_classification(n_samples={v['rows']}, n_features={v['features']}, "
                f"n_informative={inf}, n_redundant={max(0, min(2, int(v['features']) - inf))}, random_state=42)")
        imp = "from sklearn.datasets import make_classification"
    return lines(imp, "import pandas as pd", f"_X, _y = {make}",
                 f"{out} = pd.DataFrame(_X, columns=[f'feature_{{i}}' for i in range({v['features']})])",
                 f"{out}['target'] = _y")


def manual_input(v: V) -> str:
    cols = items(v["columns"])
    rows = [[c.strip() for c in ln.split(",")] for ln in str(v["data"]).strip().splitlines() if ln.strip()]
    out = v["out_dataset"]
    return lines("import pandas as pd", f"{out} = pd.DataFrame({rows!r}, columns={cols!r})",
                 f"for _c in {out}.columns:  # numbers become numeric, everything else stays text",
                 f"    try:\n        {out}[_c] = pd.to_numeric({out}[_c])\n    except (ValueError, TypeError):\n        pass")


def data_merge(v: V) -> str:
    keys = items(v["on"])
    key = keys if len(keys) > 1 else keys[0]
    return lines("import pandas as pd", f"{v['out_dataset']} = pd.merge({v['in_left']}, {v['in_right']}, on={key!r}, how={v['how']!r})")


def data_sample(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    if float(v["frac"]) > 0:
        return lines(f"{out} = {src}.sample(frac={min(float(v['frac']), 1.0)}, random_state={v['random_state']})")
    return lines(f"{out} = {src}.sample(n=min({v['n']}, len({src})), random_state={v['random_state']})")


# ---- data quality ----------------------------------------------------------------------------------

def imputer(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    cols = items(v["cols"])
    strategy = v["strategy"]
    if strategy == "knn":
        imp, ctor = "from sklearn.impute import KNNImputer", "KNNImputer()"
    else:
        imp = "from sklearn.impute import SimpleImputer"
        if strategy == "mode":
            ctor = "SimpleImputer(strategy='most_frequent')"
        elif strategy == "constant":
            try:
                fill: Any = float(v["fill_value"])
            except ValueError:
                fill = v["fill_value"]
            ctor = f"SimpleImputer(strategy='constant', fill_value={fill!r})"
        else:
            ctor = f"SimpleImputer(strategy={strategy!r})"
    pick = f"{cols!r}" if cols else f"{out}.select_dtypes(include='number').columns.tolist()"
    return lines("import pandas as pd", imp, f"{out} = {src}.copy()",
                 f"_cols = [c for c in {pick} if c in {out}.columns and pd.api.types.is_numeric_dtype({out}[c])]",
                 f"if _cols:\n    {out}[_cols] = {ctor}.fit_transform({out}[_cols])")


def dup_remover(v: V) -> str:
    keep = False if v["keep"] == "none" else v["keep"]
    subset = items(v["subset"]) or None
    return lines(f"{v['out_dataset']} = {v['in_dataset']}.drop_duplicates(subset={subset!r}, keep={keep!r})")


def outlier(v: V) -> str:
    src, out, outl = v["in_dataset"], v["out_dataset"], v["out_outliers"]
    cols = items(v["cols"])
    if not cols:
        pick = "_num"
    elif v["col_mode"] == "include":
        pick = f"[c for c in {cols!r} if c in _num]"
    else:
        pick = f"[c for c in _num if c not in {cols!r}]"
    method = v["method"]
    if method == "IQR":
        mask = ("_mask = pd.Series(True, index=_df.index)\nfor _c in _cols:\n"
                "    _q1, _q3 = _df[_c].quantile(0.25), _df[_c].quantile(0.75)\n"
                "    _mask &= _df[_c].between(_q1 - 1.5 * (_q3 - _q1), _q3 + 1.5 * (_q3 - _q1))")
        imp = ""
    elif method == "Z-Score":
        mask = ("_f = _df[_cols].fillna(0)\n"
                f"_mask = (((_f - _f.mean()) / _f.std().replace(0, 1)).abs() < {float(v['threshold'])}).all(axis=1)")
        imp = ""
    else:
        mask = "_mask = pd.Series(IsolationForest(contamination=0.1, random_state=42).fit_predict(_df[_cols].fillna(0)) == 1, index=_df.index)"
        imp = "from sklearn.ensemble import IsolationForest"
    action = v["action"]
    if action == "remove":
        result = f"{out} = _df[_mask]"
    elif action == "clip":
        result = (f"{out} = _df.copy()\nfor _c in _cols:\n    _q1, _q3 = _df[_c].quantile(0.25), _df[_c].quantile(0.75)\n"
                  f"    {out}[_c] = _df[_c].clip(_q1 - 1.5 * (_q3 - _q1), _q3 + 1.5 * (_q3 - _q1))")
    else:
        result = f"{out} = _df.copy()\n{out}['is_outlier'] = (~_mask).astype(int)"
    return lines("import pandas as pd", imp, f"_df = {src}.copy()",
                 "_num = _df.select_dtypes(include='number').columns.tolist()", f"_cols = {pick}",
                 "if not _cols:\n    _mask = pd.Series(True, index=_df.index)\nelse:\n" + "\n".join("    " + ln for ln in mask.splitlines()),
                 f"{outl} = _df[~_mask]", result)


def col_rename(v: V) -> str:
    mapping = {str(m.get("key", "")).strip(): str(m.get("values", "")).strip() for m in v["mappings"]
               if str(m.get("key", "")).strip() and str(m.get("values", "")).strip()}
    return lines(f"{v['out_dataset']} = {v['in_dataset']}.rename(columns={mapping!r})")


def type_conv(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    names = {"float": "float", "float64": "float", "int": "int", "int64": "int", "str": "str", "string": "str", "bool": "bool"}
    body = [f"{out} = {src}.copy()"]
    imp = ""
    for line in str(v["rules"]).splitlines():
        if ":" not in line:
            continue
        col, dtype = (p.strip() for p in line.split(":", 1))
        if dtype.lower() in ("datetime", "date"):
            imp = "import pandas as pd"
            body.append(f"{out}[{col!r}] = pd.to_datetime({out}[{col!r}], errors='coerce')")
        elif dtype.lower() in names:
            body.append(f"{out}[{col!r}] = {out}[{col!r}].astype({names[dtype.lower()]})")
    return lines(imp, *body)


def validator(v: V) -> str:
    schema = json.loads(v["schema"])
    src = v["in_dataset"]
    return lines(
        "import pandas as pd",
        f"_schema = {schema!r}", "_issues = []",
        "for _col, _expected in _schema.items():",
        f"    if _col not in {src}.columns:\n        _issues.append(f'Missing column: {{_col}}')",
        f"    elif _expected in ('float', 'int', 'number') and not pd.api.types.is_numeric_dtype({src}[_col]):",
        f"        _issues.append(f\"'{{_col}}' expected numeric, got {{{src}[_col].dtype}}\")",
        f"    elif _expected in ('str', 'string', 'object') and not pd.api.types.is_object_dtype({src}[_col]):",
        f"        _issues.append(f\"'{{_col}}' expected string, got {{{src}[_col].dtype}}\")",
        "if _issues:\n    " + ("raise ValueError('Validation failed: ' + '; '.join(_issues))" if v["strict"] else "print('Validation issues:', _issues)"),
        f"{v['out_dataset']} = {src}",
        f"{v['out_report']} = {{'issues': _issues, 'columns_checked': len(_schema), 'issues_found': len(_issues)}}",
    )


# ---- feature engineering ---------------------------------------------------------------------------

SCALERS = {"StandardScaler", "MinMaxScaler", "RobustScaler", "MaxAbsScaler"}


def scaler(v: V) -> str:
    src, out, tr = v["in_dataset"], v["out_dataset"], v["out_transformer"]
    method = v["method"] if v["method"] in SCALERS else "StandardScaler"
    cols = items(v["cols"])
    pick = (f"[c for c in {cols!r} if c in {out}.columns]" if cols
            else f"[c for c in {out}.select_dtypes(include='number').columns if c != 'target']")
    return lines(f"from sklearn.preprocessing import {method}", f"{out} = {src}.copy()", f"{tr} = {method}()",
                 f"_cols = {pick}", f"if _cols:\n    {out}[_cols] = {tr}.fit_transform({out}[_cols])")


def ohe(v: V) -> str:
    src, out, tr = v["in_dataset"], v["out_dataset"], v["out_transformer"]
    cols = items(v["cols"])
    drop = "'first'" if v["drop"] else "None"
    pick = f"[c for c in {cols!r} if c in {src}.columns]" if cols else "[]"
    return lines(
        "import pandas as pd", "from sklearn.preprocessing import OneHotEncoder",
        f"_cats = {pick} or {src}.select_dtypes(include=['object', 'category']).columns.tolist()",
        f"{out}, {tr} = {src}.copy(), None",
        f"if _cats:\n    {tr} = OneHotEncoder(drop={drop}, sparse_output=False, handle_unknown='ignore')\n"
        f"    _enc = pd.DataFrame({tr}.fit_transform({src}[_cats]), columns={tr}.get_feature_names_out(_cats), index={src}.index)\n"
        f"    {out} = pd.concat([{src}.drop(columns=_cats), _enc], axis=1)",
    )


def label_enc(v: V) -> str:
    src, out, tr = v["in_dataset"], v["out_dataset"], v["out_transformer"]
    return lines("from sklearn.preprocessing import LabelEncoder", f"{out} = {src}.copy()", f"{tr} = {{}}",
                 f"for _c in [c for c in {items(v['cols'])!r} if c in {out}.columns]:",
                 f"    {tr}[_c] = LabelEncoder()\n    {out}[_c] = {tr}[_c].fit_transform({out}[_c].astype(str))")


def str_split(v: V) -> str:
    sep = {"space": " ", "tab": "\t", "comma": ",", "hyphen": "-", "pipe": "|", "semicolon": ";"}[v["sep"]]
    src, out, col = v["in_dataset"], v["out_dataset"], v["col"]
    if v["expand"]:
        return lines("import pandas as pd", f"_parts = {src}[{col!r}].str.split({sep!r}, expand=True)",
                     f"_parts.columns = [f'{v['prefix']}_{{i}}' for i in range(len(_parts.columns))]",
                     f"{out} = pd.concat([{src}.copy(), _parts], axis=1)")
    return lines(f"{out} = {src}.copy()", f"{out}[{col + '_split'!r}] = {src}[{col!r}].str.split({sep!r})")


def col_selector(v: V) -> str:
    cols = items(v["cols"])
    src = v["in_dataset"]
    expr = f"{src}[{cols!r}]" if v["mode"] == "include" else f"{src}.drop(columns={cols!r})"
    return lines(f"{v['out_dataset']} = {expr}")


def feat_gen(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    return lines(
        "import pandas as pd", "from sklearn.preprocessing import PolynomialFeatures",
        f"_num = [c for c in {src}.select_dtypes(include='number').columns if c != _athena_target({src})]",
        f"_poly = PolynomialFeatures(degree={v['degree']}, interaction_only={bool(v['interaction'])}, include_bias=False)",
        f"_p = pd.DataFrame(_poly.fit_transform({src}[_num]), columns=_poly.get_feature_names_out(_num), index={src}.index)",
        f"{out} = pd.concat([{src}.drop(columns=_num), _p], axis=1)",
    )


def tfidf(v: V) -> str:
    src, out, col = v["in_dataset"], v["out_dataset"], v["col"]
    cls = "TfidfVectorizer" if v["method"] == "TF-IDF" else "CountVectorizer"
    return lines(
        "import pandas as pd", f"from sklearn.feature_extraction.text import {cls}",
        f"_vec = {cls}(max_features={v['max_features']})",
        f"_mat = _vec.fit_transform({src}[{col!r}].fillna('').astype(str))",
        f"_feat = pd.DataFrame(_mat.toarray(), columns=[f'{col}_{{n}}' for n in _vec.get_feature_names_out()], index={src}.index)",
        f"{out} = pd.concat([{src}.drop(columns=[{col!r}]), _feat], axis=1)",
    )


DATE_PARTS = {"year": "_dt.dt.year", "month": "_dt.dt.month", "day": "_dt.dt.day", "weekday": "_dt.dt.weekday",
              "hour": "_dt.dt.hour", "minute": "_dt.dt.minute", "quarter": "_dt.dt.quarter",
              "week": "_dt.dt.isocalendar().week.astype(int)", "dayofyear": "_dt.dt.dayofyear",
              "is_weekend": "(_dt.dt.weekday >= 5).astype(int)"}


def date_feat(v: V) -> str:
    src, out, col = v["in_dataset"], v["out_dataset"], v["col"]
    adds = [f"{out}[{col + '_' + f!r}] = {DATE_PARTS[f]}" for f in items(v["features"]) if f in DATE_PARTS]
    return lines("import pandas as pd", f"{out} = {src}.copy()", f"_dt = pd.to_datetime({out}[{col!r}], errors='coerce')", *adds)


def feat_imp_sel(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    fn = {"chi2": "chi2", "f_classif": "f_classif", "mutual_info": "mutual_info_classif"}[v["method"]]
    return lines(
        f"from sklearn.feature_selection import SelectKBest, {fn}",
        f"_t = _athena_target({src})", f"_X = {src}.drop(columns=[_t])", "_num = _X.select_dtypes(include='number')",
        f"_sel = SelectKBest({fn}, k=min({v['k']}, len(_num.columns))).fit(_num.fillna(0), {src}[_t])",
        f"{out} = {src}[[c for c in _X.columns if c not in _num.columns] + _num.columns[_sel.get_support()].tolist() + [_t]]",
    )


def pca(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    return lines(
        "import pandas as pd", "from sklearn.decomposition import PCA",
        f"_t = _athena_target({src})", f"_X = {src}.drop(columns=[_t])", "_num = _X.select_dtypes(include='number')",
        f"_n = min({v['n_components']}, len(_num.columns), len({src}))",
        f"_pcs = PCA(n_components=_n, whiten={bool(v['whiten'])}).fit_transform(_num.fillna(0))",
        f"{out} = pd.concat([{src}[[c for c in _X.columns if c not in _num.columns]], "
        f"pd.DataFrame(_pcs, columns=[f'pc_{{i + 1}}' for i in range(_n)], index={src}.index)], axis=1)",
        f"{out}[_t] = {src}[_t].values",
    )


# ---- balancing -------------------------------------------------------------------------------------

def _resample(v: V, imp: str, ctor: str, as_values: bool) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    vals = ".values" if as_values else ""
    return lines("import pandas as pd", imp, f"_t = _athena_target({src})",
                 f"_X_res, _y_res = {ctor}.fit_resample({src}.drop(columns=[_t]){vals}, {src}[_t]{vals})",
                 f"{out} = pd.DataFrame(_X_res, columns=[c for c in {src}.columns if c != _t])", f"{out}[_t] = _y_res")


def smote(v: V) -> str:
    return _resample(v, "from imblearn.over_sampling import SMOTE",
                     f"SMOTE(k_neighbors={v['k_neighbors']}, random_state={v['random_state']})", False)


def undersample(v: V) -> str:
    ctor = {"tomek": "TomekLinks()", "enn": "EditedNearestNeighbours()"}.get(
        v["strategy"], f"RandomUnderSampler(sampling_strategy={v['ratio']}, random_state=42)")
    cls = ctor.split("(")[0]
    return _resample(v, f"from imblearn.under_sampling import {cls}", ctor, True)


def oversample(v: V) -> str:
    ctor = "ADASYN(random_state=42)" if v["strategy"] == "adasyn" else "RandomOverSampler(random_state=42)"
    return _resample(v, f"from imblearn.over_sampling import {ctor.split('(')[0]}", ctor, True)


def class_weight(v: V) -> str:
    src = v["in_dataset"]
    return lines("import numpy as np", "from sklearn.utils.class_weight import compute_class_weight",
                 f"_y = {src}[_athena_target({src})]", "_classes = np.unique(_y)",
                 "class_weights = dict(zip(_classes.tolist(), compute_class_weight('balanced', classes=_classes, y=_y).tolist()))",
                 "print('Class weights:', class_weights)", f"{v['out_dataset']} = {src}")


# ---- splits ----------------------------------------------------------------------------------------

def train_test(v: V) -> str:
    src = v["in_dataset"]
    strat = "_y" if v["stratify"] else "None"
    return lines("from sklearn.model_selection import train_test_split",
                 f"_t = _athena_target({src}, {v['target_col']!r})", f"_X, _y = {src}.drop(columns=[_t]), {src}[_t]",
                 f"{v['out_X_train']}, {v['out_X_test']}, {v['out_y_train']}, {v['out_y_test']} = train_test_split(",
                 f"    _X, _y, test_size={v['test_size']}, random_state={v['random_state']}, stratify={strat})")


def train_val_test(v: V) -> str:
    src = v["in_dataset"]
    rel = float(v["val_size"]) / (1.0 - float(v["test_size"]))
    return lines("from sklearn.model_selection import train_test_split",
                 f"_t = _athena_target({src}, {v['target_col']!r})", f"_X, _y = {src}.drop(columns=[_t]), {src}[_t]",
                 f"_X_tmp, {v['out_X_test']}, _y_tmp, {v['out_y_test']} = train_test_split(_X, _y, test_size={v['test_size']}, random_state={v['random_state']})",
                 f"{v['out_X_train']}, {v['out_X_val']}, {v['out_y_train']}, {v['out_y_val']} = train_test_split(",
                 f"    _X_tmp, _y_tmp, test_size={rel!r}, random_state={v['random_state']})")


def cv_split(v: V) -> str:
    src = v["in_dataset"]
    rs = v["random_state"] if v["shuffle"] else None
    split_args = "_X, _y" if v["method"] == "StratifiedKFold" else "_X"
    return lines(f"from sklearn.model_selection import {v['method']}",
                 f"_t = _athena_target({src}, {v['target_col']!r})", f"_X, _y = {src}.drop(columns=[_t]), {src}[_t]",
                 f"_tr, _te = list({v['method']}(n_splits={v['k']}, shuffle={bool(v['shuffle'])}, random_state={rs!r}).split({split_args}))[{int(v['fold_index']) % int(v['k'])}]",
                 f"{v['out_X_train']}, {v['out_X_test']} = _X.iloc[_tr].reset_index(drop=True), _X.iloc[_te].reset_index(drop=True)",
                 f"{v['out_y_train']}, {v['out_y_test']} = _y.iloc[_tr].reset_index(drop=True), _y.iloc[_te].reset_index(drop=True)")


def dataset_to_xy(v: V) -> str:
    src = v["in_dataset"]
    return lines(f"_t = _athena_target({src}, {v['target_col']!r})",
                 f"{v['out_X_train']}, {v['out_y_train']} = {src}.drop(columns=[_t]), {src}[_t]")


def xy_to_dataset(v: V) -> str:
    name = str(v["target_col"]).strip() or "target"
    return lines("import pandas as pd", f"{v['out_dataset']} = {v['in_X_train']}.join(pd.Series({v['in_y_train']}, name={name!r}), how='inner')")


EXPORT: dict[str, Template] = {f.__name__: f for f in [
    csv_loader, excel_loader, json_loader, parquet_loader, synth_data, manual_input, data_merge, data_sample,
    imputer, dup_remover, outlier, col_rename, type_conv, validator,
    scaler, ohe, label_enc, str_split, col_selector, feat_gen, tfidf, date_feat, feat_imp_sel, pca,
    smote, undersample, oversample, class_weight,
    train_test, train_val_test, cv_split, dataset_to_xy, xy_to_dataset,
]}
