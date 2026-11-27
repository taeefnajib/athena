"""Export templates: probability calibration, calibration curve, decision threshold.

They call the same helpers the handlers use (``_athena_tuning_scores``, ``_athena_threshold``), which codegen
copies verbatim from athena/nodes/calibration.py into the script.
"""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]


def _has_val(v: V) -> bool:
    return v["in_X_val"] != "None" and v["in_y_val"] != "None"


def calibrate(v: V) -> str:
    m, out = v["in_model"], v["out_model"]
    if _has_val(v):
        return lines("from sklearn.calibration import CalibratedClassifierCV", "from sklearn.frozen import FrozenEstimator",
                     f"# Calibrate the fitted model on the validation set ({v['method']})",
                     f"{out} = CalibratedClassifierCV(FrozenEstimator({m}), method={v['method']!r}).fit({v['in_X_val']}, {v['in_y_val']})")
    return lines("from sklearn.base import clone", "from sklearn.calibration import CalibratedClassifierCV",
                 "from sklearn.model_selection import StratifiedKFold",
                 f"# Calibrate with {v['cv']}-fold cross-validation on the training set ({v['method']})",
                 f"{out} = CalibratedClassifierCV(clone({m}), method={v['method']!r}, "
                 f"cv=StratifiedKFold(n_splits={v['cv']}, shuffle=True, random_state=0)).fit({v['in_X_train']}, {v['in_y_train']})")


def calibration_curve(v: V) -> str:
    m, X, y, f = v["in_model"], v["in_X_test"], v["in_y_test"], v["out_plot"]
    bins = int(v["n_bins"])
    return lines(
        "import matplotlib.pyplot as plt", "import numpy as np",
        "from sklearn.calibration import calibration_curve", "from sklearn.metrics import brier_score_loss",
        f"_scores, _is_pos, _pos = _athena_tuning_scores({m}, None, {y}, {X}, {y}, positive={v['positive_class']!r})",
        f"_frac, _mean = calibration_curve(_is_pos, _scores, n_bins={bins}, strategy={v['strategy']!r})",
        "_brier = brier_score_loss(_is_pos, _scores)",
        f"_counts, _edges = np.histogram(_scores, bins=np.linspace(0, 1, {bins + 1}))",
        f"_bins = np.clip(np.digitize(_scores, _edges[1:-1]), 0, {bins - 1})",
        f"_ece = sum(abs(_is_pos[_bins == b].mean() - _scores[_bins == b].mean()) * (_bins == b).mean() for b in range({bins}) if (_bins == b).any())",
        "print('Brier score', round(_brier, 4), '| expected calibration error', round(_ece, 4))",
        f"{f}, (_ax, _axh) = plt.subplots(2, 1, figsize=(6, 6), height_ratios=[3, 1], sharex=True)",
        "_ax.plot([0, 1], [0, 1], color='#999999', lw=1, linestyle=(0, (4, 3)))",
        "_ax.plot(_mean, _frac, color='#257de0', lw=2, marker='o', markersize=5, markeredgecolor='white')",
        "_ax.set_ylabel(f'Observed share of {_pos}'); _ax.set_ylim(0, 1)",
        "_ax.set_title(f'Calibration curve · Brier {_brier:.3f} · ECE {_ece:.3f}', loc='left')",
        "_axh.bar(_edges[:-1], _counts, width=np.diff(_edges) - 0.004, align='edge', color='#257de0', alpha=0.35)",
        "_axh.set_xlabel('Predicted probability'); _axh.set_ylabel('Rows'); _axh.set_xlim(0, 1)",
        f"{f}.tight_layout()", f"{f}.savefig({v['id'] + '_calibration.png'!r}, dpi=100)",
    )


def threshold_tune(v: V) -> str:
    m, out, rep = v["in_model"], v["out_model"], v["out_report"]
    X, y = v["in_X_train"], v["in_y_train"]
    val = f"{v['in_X_val']}, {v['in_y_val']}" if _has_val(v) else "None, None"
    return lines(
        "import numpy as np", "from sklearn.frozen import FrozenEstimator", "from sklearn.model_selection import FixedThresholdClassifier",
        f"# Tune the decision threshold ({v['objective']}) on data the model didn't fit on",
        f"_scores, _is_pos, _pos = _athena_tuning_scores({m}, {X}, {y}, {val}, cv={v['cv']}, positive={v['positive_class']!r})",
        f"_t, _table = _athena_threshold(_scores, _is_pos, {v['objective']!r}, {v['constraint']}, {v['cost_fp']}, {v['cost_fn']})",
        f"{out} = FixedThresholdClassifier(FrozenEstimator({m}), threshold=_t, pos_label=_pos, response_method='predict_proba').fit({X}, {y})",
        "_i, _d = (int(np.argmin(np.abs(_table['threshold'] - t))) for t in (_t, 0.5))",
        f"{rep} = {{'threshold': _t, **{{k: float(_table[k][_i]) for k in ('precision', 'recall', 'f1', 'balanced_accuracy', 'cost')}},",
        "    **{f'{k}_at_0.5': float(_table[k][_d]) for k in ('precision', 'recall', 'f1', 'balanced_accuracy', 'cost')}}",
        f"print('Threshold', round(_t, 4), {rep})",
    )


def pr_curve(v: V) -> str:
    m, X, y, f = v["in_model"], v["in_X_test"], v["in_y_test"], v["out_plot"]
    pos = str(v["positive_class"]).strip()
    return lines(
        "import matplotlib.pyplot as plt", "import numpy as np",
        "from sklearn.metrics import average_precision_score, precision_recall_curve",
        f"_y, _proba = np.asarray({y}), {m}.predict_proba({X})",
        f"_classes = list(getattr({m}, 'classes_', np.unique(_y)))",
        "if len(_classes) == 2:\n"
        f"    _pos = next(c for c in _classes if str(c) == {pos!r}) if {pos!r} else _classes[1]\n"
        "    _curves = [(str(_pos), _y == _pos, _proba[:, _classes.index(_pos)])]\n"
        "else:\n"
        "    _curves = [(str(c), _y == c, _proba[:, i]) for i, c in enumerate(_classes)]",
        f"{f}, _ax = plt.subplots(figsize=(6.4, 5))",
        "_colors = ['#257de0', '#f47230', '#00b894', '#f2a600', '#ee7fac', '#008a17', '#6a4ce2', '#ec4647']",
        "for (_name, _is_pos, _score), _c in zip(_curves, _colors):\n"
        "    _p, _r, _ = precision_recall_curve(_is_pos, _score)\n"
        "    _ax.step(_r, _p, where='post', color=_c, lw=2, label=f'Class {_name} · AP {average_precision_score(_is_pos, _score):.3f}')",
        "_ax.set_xlabel('Recall'); _ax.set_ylabel('Precision'); _ax.set_xlim(0, 1); _ax.set_ylim(0, 1.02)",
        "_ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1), frameon=False)",
        f"{f}.tight_layout()", f"{f}.savefig({v['id'] + '_pr_curve.png'!r}, dpi=100)",
    )


EXPORT: dict[str, Template] = {"calibrate": calibrate, "calibration_curve": calibration_curve, "threshold_tune": threshold_tune, "pr_curve": pr_curve}
