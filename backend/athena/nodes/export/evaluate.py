"""Export templates: evaluation, interpretability, deployment and monitoring. Plots are saved as PNG files
next to the script (``<node id>_<kind>.png``), because a script has no inspector to show them in."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, items, lines

V = dict[str, Any]


def _save(v: V, fig: str, kind: str) -> str:
    name = f"{v['id']}_{kind}.png"
    return f"{fig}.savefig({name!r}, dpi=100)\nprint('Saved', {name!r})"


def metrics(v: V) -> str:
    m, X, y, out = v["in_model"], v["in_X_test"], v["in_y_test"], v["out_report"]
    if v["task"] == "regression":
        return lines("import numpy as np", "from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score",
                     f"_pred = {m}.predict({X})",
                     f"{out} = {{'rmse': float(np.sqrt(mean_squared_error({y}, _pred))), 'mae': float(mean_absolute_error({y}, _pred)), "
                     f"'r2': float(r2_score({y}, _pred))}}", f"print({out})")
    avg = v["average"]
    return lines(
        "from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score",
        f"_pred = {m}.predict({X})",
        f"{out} = {{'accuracy': float(accuracy_score({y}, _pred)),",
        f"    'precision': float(precision_score({y}, _pred, average={avg!r}, zero_division=0)),",
        f"    'recall': float(recall_score({y}, _pred, average={avg!r}, zero_division=0)),",
        f"    'f1': float(f1_score({y}, _pred, average={avg!r}, zero_division=0))}}",
        f"if hasattr({m}, 'predict_proba'):\n    _proba = {m}.predict_proba({X})\n"
        f"    {out}['roc_auc'] = float(roc_auc_score({y}, _proba[:, 1]) if _proba.shape[1] == 2 else roc_auc_score({y}, _proba, multi_class='ovr'))",
        f"print({out})",
    )


def conf_matrix(v: V) -> str:
    norm = None if v["normalize"] == "none" else v["normalize"]
    f = v["out_plot"]
    return lines("import matplotlib.pyplot as plt", "from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix",
                 f"{f}, _ax = plt.subplots(figsize=(6, 5))",
                 f"ConfusionMatrixDisplay(confusion_matrix={_cm(v, norm)}).plot(ax=_ax, cmap={v['cmap']!r}, colorbar=False)",
                 "_ax.set_title('Confusion Matrix')", f"{f}.tight_layout()", _save(v, f, "confusion_matrix"))


def _cm(v: V, norm: Any) -> str:
    return f"confusion_matrix({v['in_y_test']}, {v['in_model']}.predict({v['in_X_test']}), normalize={norm!r})"


def residual(v: V) -> str:
    f = v["out_plot"]
    return lines("import matplotlib.pyplot as plt", "import numpy as np",
                 f"_pred = {v['in_model']}.predict({v['in_X_test']})", f"_res = np.array({v['in_y_test']}) - np.array(_pred)",
                 f"{f}, _axes = plt.subplots(1, 2, figsize=(10, 4))",
                 "_axes[0].scatter(_pred, _res, alpha=0.5, s=20)", "_axes[0].axhline(0, color='red', linestyle='--', linewidth=1)",
                 "_axes[0].set_xlabel('Predicted'); _axes[0].set_ylabel('Residual'); _axes[0].set_title('Residuals vs Predicted')",
                 "_axes[1].hist(_res, bins=30, edgecolor='white', linewidth=0.5)",
                 "_axes[1].set_xlabel('Residual'); _axes[1].set_title('Residual Distribution')",
                 f"{f}.tight_layout()", _save(v, f, "residuals"))


def roc_curve(v: V) -> str:
    f, m, X, y = v["out_plot"], v["in_model"], v["in_X_test"], v["in_y_test"]
    return lines("import matplotlib.pyplot as plt", "import numpy as np",
                 "from sklearn.metrics import auc, roc_curve", "from sklearn.preprocessing import label_binarize",
                 f"_classes, _proba = np.unique({y}), {m}.predict_proba({X})", f"{f}, _ax = plt.subplots(figsize=(6, 5))",
                 f"if len(_classes) == 2:\n    _fpr, _tpr, _ = roc_curve({y}, _proba[:, 1])\n"
                 "    _ax.plot(_fpr, _tpr, lw=2, label=f'AUC = {auc(_fpr, _tpr):.3f}')\nelse:\n"
                 f"    _yb = label_binarize({y}, classes=_classes)\n    for _i, _c in enumerate(_classes):\n"
                 "        _fpr, _tpr, _ = roc_curve(_yb[:, _i], _proba[:, _i])\n"
                 "        _ax.plot(_fpr, _tpr, lw=1.5, label=f'Class {_c} (AUC={auc(_fpr, _tpr):.2f})')",
                 "_ax.plot([0, 1], [0, 1], 'k--', lw=1)", "_ax.set_xlabel('False Positive Rate'); _ax.set_ylabel('True Positive Rate')",
                 "_ax.set_title('ROC Curve'); _ax.legend(loc='lower right', fontsize=9)", f"{f}.tight_layout()", _save(v, f, "roc_curve"))


def feat_imp_viz(v: V) -> str:
    f, m = v["out_plot"], v["in_model"]
    return lines("import matplotlib.pyplot as plt", "import numpy as np",
                 f"_imp = {m}.feature_importances_ if hasattr({m}, 'feature_importances_') else "
                 f"(np.abs({m}.coef_).mean(axis=0) if np.ndim({m}.coef_) > 1 else np.abs({m}.coef_))",
                 f"_names = getattr({m}, 'feature_names_in_', [f'f{{i}}' for i in range(len(_imp))])",
                 f"_idx = np.argsort(_imp)[-{int(v['top_n'])}:]",
                 f"{f}, _ax = plt.subplots(figsize=(7, max(4, len(_idx) * 0.3)))",
                 "_ax.barh(range(len(_idx)), _imp[_idx]); _ax.set_yticks(range(len(_idx)))",
                 "_ax.set_yticklabels([_names[i] for i in _idx], fontsize=8); _ax.set_xlabel('Importance')",
                 "_ax.set_title(f'Top {len(_idx)} Feature Importances')", f"{f}.tight_layout()", _save(v, f, "feature_importance"))


def df_info(v: V) -> str:
    src = v["in_dataset"]
    return lines(f"print({src}.shape, 'rows x cols;', int({src}.duplicated().sum()), 'duplicates;', int({src}.isnull().sum().sum()), 'missing cells')",
                 f"print({src}.describe(include='all').T)", f"{v['out_dataset']} = {src}")


def data_viz(v: V) -> str:
    """Matplotlib versions of the charts (Athena uses seaborn styling when seaborn is installed)."""
    src, f, kind = v["in_dataset"], v["out_plot"], v["chart_type"]
    x, y, col = str(v["x_col"]).strip(), str(v["y_col"]).strip(), str(v["col"]).strip()
    title = v["title"] or f"{kind} Chart"
    head = [f"_num = {src}.select_dtypes(include='number').columns.tolist()", f"{f}, _ax = plt.subplots(figsize=(8, 5))"]
    if kind == "Histogram":
        body = [f"_c = {(col or x)!r} if {(col or x)!r} in {src}.columns else (_num[0] if _num else {src}.columns[0])",
                f"_ax.hist({src}[_c].dropna(), bins={int(v['bins'])}); _ax.set_xlabel(_c)"]
    elif kind == "Bar":
        body = [f"_x = {x!r} if {x!r} in {src}.columns else {src}.columns[0]",
                (f"_g = {src}.groupby(_x)[{y!r}].mean(); _ax.bar(_g.index.astype(str), _g.values); _ax.set_ylabel({y!r})" if y else
                 f"_vc = {src}[_x].value_counts().head(20); _ax.bar(_vc.index.astype(str), _vc.values); _ax.set_ylabel('Count')"),
                "_ax.set_xlabel(_x); plt.xticks(rotation=45, ha='right')"]
    elif kind in ("Line", "Scatter"):
        xd = f"{src}.columns[0]" if kind == "Line" else f"(_num[0] if _num else {src}.columns[0])"
        yd = f"(_num[0] if _num else {src}.columns[0])" if kind == "Line" else f"(_num[1] if len(_num) > 1 else {src}.columns[0])"
        draw = f"_ax.plot({src}[_x], {src}[_y])" if kind == "Line" else f"_ax.scatter({src}[_x], {src}[_y], alpha=0.5, s=20)"
        body = [f"_x = {x!r} if {x!r} in {src}.columns else {xd}", f"_y = {y!r} if {y!r} in {src}.columns else {yd}",
                draw, "_ax.set_xlabel(_x); _ax.set_ylabel(_y)"]
    elif kind == "Pie":
        body = [f"_c = {(col or x)!r} if {(col or x)!r} in {src}.columns else {src}.columns[0]",
                f"_vc = {src}[_c].value_counts().head(10)", "_ax.pie(_vc.values, labels=_vc.index.astype(str), autopct='%1.1f%%'); _ax.set_aspect('equal')"]
    elif kind in ("Box", "Violin"):
        yy = y or col
        body = [f"_y = {yy!r} if {yy!r} in {src}.columns else (_num[0] if _num else {src}.columns[0])",
                (f"_ax.boxplot([g.dropna().values for _, g in {src}.groupby({x!r})[_y]], labels=[str(k) for k in {src}[{x!r}].unique()])"
                 if x else f"_ax.boxplot({src}[_y].dropna())"), "_ax.set_ylabel(_y)"]
    else:  # Heatmap
        body = [f"_corr = {src}[_num[:20]].corr()", f"_im = _ax.imshow(_corr.values, aspect='auto', cmap={v['palette']!r}, vmin=-1, vmax=1)",
                f"{f}.colorbar(_im, ax=_ax); _ax.set_xticks(range(len(_corr.columns))); _ax.set_yticks(range(len(_corr.columns)))",
                "_ax.set_xticklabels(_corr.columns, rotation=90, fontsize=8); _ax.set_yticklabels(_corr.columns, fontsize=8)"]
    return lines("import matplotlib.pyplot as plt", *head, *body, f"_ax.set_title({title!r})", f"{f}.tight_layout()",
                 _save(v, f, kind.lower()))


def corr_check(v: V) -> str:
    src, f = v["in_dataset"], v["out_plot"]
    if v["mode"] == "Pairwise":
        c1, c2 = str(v["col1"]).strip(), str(v["col2"]).strip()
        return lines("import matplotlib.pyplot as plt", f"{f}, _axes = plt.subplots(1, 2, figsize=(10, 4))",
                     f"_r = {src}[{c1!r}].corr({src}[{c2!r}], method={v['method']!r})",
                     f"_axes[0].scatter({src}[{c1!r}], {src}[{c2!r}], alpha=0.5, s=20)",
                     f"_axes[0].set_xlabel({c1!r}); _axes[0].set_ylabel({c2!r}); _axes[0].set_title(f'{c1} vs {c2}\\n{v['method']} r = {{_r:.3f}}')",
                     f"_v = {src}[[{c1!r}, {c2!r}]].dropna()", f"_axes[1].hist2d(_v[{c1!r}], _v[{c2!r}], bins=20, cmap={v['cmap']!r})",
                     "_axes[1].set_title('Joint Distribution')", f"{f}.tight_layout()", _save(v, f, "correlation"))
    return lines("import matplotlib.pyplot as plt",
                 f"_num = {src}.select_dtypes(include='number')", f"_n = min({int(v['top_n'])}, len(_num.columns))",
                 f"_corr = _num.iloc[:, :_n].corr(method={v['method']!r})",
                 f"{f}, _ax = plt.subplots(figsize=(max(6, _n * 0.5), max(5, _n * 0.45)))",
                 f"_im = _ax.imshow(_corr.values, aspect='auto', cmap={v['cmap']!r}, vmin=-1, vmax=1); {f}.colorbar(_im, ax=_ax)",
                 "_ax.set_xticks(range(_n)); _ax.set_yticks(range(_n))",
                 "_ax.set_xticklabels(_corr.columns, rotation=90, fontsize=8); _ax.set_yticklabels(_corr.columns, fontsize=8)",
                 f"_ax.set_title('Correlation Matrix ({str(v['method']).title()})')", f"{f}.tight_layout()", _save(v, f, "correlation"))


def class_dist(v: V) -> str:
    src, f = v["in_dataset"], v["out_plot"]
    pct = "'%1.1f%%'" if v["show_percent"] else "None"
    return lines("import matplotlib.pyplot as plt",
                 f"_t = _athena_target({src}, {v['target_col']!r})", f"_vc = {src}[_t].value_counts()",
                 f"{f}, _axes = plt.subplots(1, 2, figsize=(10, 4))",
                 "_axes[0].bar(_vc.index.astype(str), _vc.values); _axes[0].set_xlabel(_t); _axes[0].set_ylabel('Count')",
                 "_axes[0].set_title(f'Class Distribution — {_t}')",
                 f"_axes[1].pie(_vc.values, labels=_vc.index.astype(str), autopct={pct}); _axes[1].set_title('Proportions')",
                 "print('Imbalance ratio:', _vc.max() / _vc.min())", f"{f}.tight_layout()", _save(v, f, "class_distribution"))


def shap(v: V) -> str:
    m, X = v["in_model"], v["in_X_test"]
    return lines("import matplotlib.pyplot as plt", "import shap",
                 f"_sample = {X}.head({int(v['n_samples'])})",
                 f"try:\n    _sv = shap.TreeExplainer({m}).shap_values(_sample)\nexcept Exception:\n"
                 f"    try:\n        _sv = shap.LinearExplainer({m}, _sample).shap_values(_sample)\n    except Exception:\n"
                 f"        _sv = shap.KernelExplainer({m}.predict, shap.sample(_sample, 50)).shap_values(_sample, nsamples=50)",
                 "_sv = _sv[0] if isinstance(_sv, list) else _sv",
                 f"shap.summary_plot(_sv, _sample, plot_type={'bar' if v['plot'] == 'bar' else 'dot'!r}, show=False, max_display=20)",
                 f"{v['out_report']} = plt.gcf()", "plt.tight_layout()", _save(v, v["out_report"], "shap"))


def debugger(v: V) -> str:
    m, X, y = v["in_model"], v["in_X_test"], v["in_y_test"]
    return lines("import numpy as np", f"_pred = {m}.predict({X})", f"_err = np.abs(np.array({y}) - np.array(_pred))",
                 "_worst = np.argsort(_err)[-10:][::-1]", "print('10 worst predictions:')",
                 f"for _i in _worst:\n    print(f'  idx={{_i}}  true={{{y}.iloc[_i]!r}}  pred={{_pred[_i]!r}}  err={{_err[_i]:.4f}}')",
                 f"{v['out_report']} = {{'worst_errors': _err[_worst].tolist(), 'mean_error': float(_err.mean())}}")


# ---- deployment ------------------------------------------------------------------------------------

def _predict(v: V, model: str, src: str, out: str) -> str:
    col = v["output_col"]
    if v["proba"]:
        return (f"{out} = {src}.copy()\nif hasattr({model}, 'predict_proba'):\n    _p = {model}.predict_proba({out})\n"
                f"    for _i, _c in enumerate(getattr({model}, 'classes_', range(_p.shape[1]))):\n        {out}[f'{col}_proba_{{_c}}'] = _p[:, _i]\n"
                f"else:\n    {out}[{col!r}] = {model}.predict({out})")
    return f"{out} = {src}.copy()\n{out}[{col!r}] = {model}.predict({out})"


def predict(v: V) -> str:
    return lines(_predict(v, v["in_model"], v["in_dataset"], v["out_predictions"]))


def model_loader(v: V) -> str:
    return lines("import joblib", f"_model_{v['var']} = joblib.load({v['path']!r})  # reads joblib and pickle files",
                 _predict(v, f"_model_{v['var']}", v["in_dataset"], v["out_predictions"]))


def csv_export(v: V) -> str:
    return lines("from pathlib import Path", f"Path({v['path']!r}).parent.mkdir(parents=True, exist_ok=True)",
                 f"{v['in_dataset']}.to_csv({v['path']!r}, index={bool(v['index'])})")


def model_saver(v: V) -> str:
    if v["format"] == "pickle":
        return lines("import pickle", f"with open({v['path']!r}, 'wb') as _f:\n    pickle.dump({v['in_model']}, _f)")
    return lines("import joblib", f"joblib.dump({v['in_model']}, {v['path']!r})")


def pred_print(v: V) -> str:
    src, col = v["in_predictions"], str(v["pred_col"]).strip() or "y_pred"
    pick = src if v["show_input"] else f"{src}[[c for c in {src}.columns if c == {col!r} or c.startswith({col + '_proba_'!r})]]"
    return lines(f"print({pick}.head(200))")


def report_gen(v: V) -> str:
    note = "" if v["format"] == "HTML" else f"# Athena can also write {v['format']}; the export writes the HTML version.\n"
    path = str(v["path"]).rsplit(".", 1)[0] + ".html"
    src = v["in_report"]
    return lines(note.rstrip("\n"), "import html as _html",
                 f"_rows = ''.join(f'<tr><td>{{k}}</td><td>{{v:.4f}}</td></tr>' if isinstance(v, float) else f'<tr><td>{{k}}</td><td>{{_html.escape(str(v))}}</td></tr>' "
                 f"for k, v in {src}.items()) if isinstance({src}, dict) else f'<tr><td colspan=2><pre>{{_html.escape(str({src}))}}</pre></td></tr>'",
                 f"with open({path!r}, 'w', encoding='utf-8') as _f:\n"
                 "    _f.write(f\"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Athena Report</title></head>\"\n"
                 "             f\"<body><h1>Pipeline Report</h1><table>{_rows}</table></body></html>\")",
                 f"print('Saved', {path!r})")


def transformer_save(v: V) -> str:
    return lines("import pickle", f"with open({v['path']!r}, 'wb') as _f:\n    pickle.dump({v['in_transformer']}, _f)",
                 f"{v['out_dataset']} = {v['in_dataset']}")


def transformer_load(v: V) -> str:
    src, out = v["in_dataset"], v["out_dataset"]
    cols = items(v["cols"])
    return lines(
        "import pickle", "import pandas as pd",
        f"with open({v['path']!r}, 'rb') as _f:\n    _tr = pickle.load(_f)", f"{out} = {src}.copy()",
        "if isinstance(_tr, dict):  # label encoders, one per column\n"
        f"    for _c in {cols!r} or list(_tr):\n        if _c in _tr and _c in {out}.columns:\n"
        f"            {out}[_c] = _tr[_c].transform({out}[_c].astype(str))\nelse:\n"
        f"    _cols = {cols!r} or [c for c in getattr(_tr, 'feature_names_in_', {out}.select_dtypes(include='number').columns) if c in {out}.columns]\n"
        f"    _t = _tr.transform({out}[_cols].to_numpy())\n    _t = _t.toarray() if hasattr(_t, 'toarray') else _t\n"
        f"    if _t.shape[1] == len(_cols):\n        {out}[_cols] = _t\n    else:\n"
        f"        _names = list(_tr.get_feature_names_out()) if hasattr(_tr, 'get_feature_names_out') else [f'feat_{{i}}' for i in range(_t.shape[1])]\n"
        f"        {out} = pd.concat([{out}.drop(columns=_cols), pd.DataFrame(_t, columns=_names, index={out}.index)], axis=1)",
    )


# ---- monitoring ------------------------------------------------------------------------------------

def drift_detect(v: V) -> str:
    cur, ref = v["in_dataset"], v["in_reference"]
    psi = v["method"] == "PSI"
    score = ("    _bp = np.unique(np.percentile(_r, np.linspace(0, 100, 11)))\n"
             "    _e = np.histogram(_r, bins=_bp)[0] + 1e-6; _a = np.histogram(_c, bins=_bp)[0] + 1e-6\n"
             "    _e, _a = _e / _e.sum(), _a / _a.sum()\n    _scores[_col] = float(np.sum((_a - _e) * np.log(_a / _e)))"
             if psi else
             "    _all = np.sort(np.concatenate([_r, _c]))\n"
             "    _scores[_col] = float(np.max(np.abs(np.searchsorted(np.sort(_r), _all, side='right') / len(_r)\n"
             "                                        - np.searchsorted(np.sort(_c), _all, side='right') / len(_c))))")
    limit = 0.2 if psi else float(v["threshold"])
    return lines(
        "import numpy as np", "import pandas as pd", "_scores = {}",
        f"for _col in [c for c in {cur}.columns if c in {ref}.columns and pd.api.types.is_numeric_dtype({cur}[c])]:",
        f"    _c, _r = {cur}[_col].dropna().values, {ref}[_col].dropna().values\n    if len(_c) == 0 or len(_r) == 0:\n        continue",
        score, f"_drifted = [c for c, s in _scores.items() if s > {limit}]",
        "print('Drifted columns:', _drifted)",
        f"{v['out_report']} = {{'drifted_columns': len(_drifted), 'columns_checked': len(_scores), **_scores}}",
    )


def perf_tracker(v: V) -> str:
    src, m, out = v["in_dataset"], v["in_model"], v["out_report"]
    metric = {"accuracy": ("accuracy_score", "accuracy_score(_y, _pred)"),
              "f1": ("f1_score", "f1_score(_y, _pred, average='weighted', zero_division=0)"),
              "rmse": ("mean_squared_error", "np.sqrt(mean_squared_error(_y, _pred))")}[v["metric"]]
    return lines("import numpy as np", f"from sklearn.metrics import {metric[0]}",
                 f"_t = _athena_target({src})", f"_y = {src}[_t]", f"_pred = {m}.predict({src}.drop(columns=[_t]))",
                 f"{out} = {{{v['metric']!r}: float({metric[1]}), 'samples': float(len(_y))}}", f"print({out})")


EXPORT: dict[str, Template] = {f.__name__: f for f in [
    metrics, conf_matrix, residual, roc_curve, feat_imp_viz, df_info, data_viz, corr_check, class_dist,
    shap, debugger, predict, model_loader, csv_export, model_saver, pred_print, report_gen,
    transformer_save, transformer_load, drift_detect, perf_tracker,
]}
