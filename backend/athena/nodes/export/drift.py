"""Export templates: the Evidently monitoring nodes. They call the same helpers as the nodes
(``_athena_evidently_drift``, ``_athena_prediction_drift``, ``_athena_data_quality``), copied verbatim into the script.
Saving the interactive HTML report is left as a commented line, so the script writes no files unless asked."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]


def _html(v: V, what: str) -> str:
    return f"# _snapshot.save_html('{what}_{v['var']}.html')  # Evidently's full interactive report"


def _methods(v: V) -> str:
    return f"{v['num_method']!r}, {v['cat_method']!r}, {float(v['num_threshold'])!r}, {float(v['cat_threshold'])!r}"


def evidently_drift(v: V) -> str:
    rep, cols = v["out_report"], v["out_columns"]
    return lines(
        f"{rep}, {cols}, _snapshot = _athena_evidently_drift({v['in_current']}, {v['in_reference']}, {v['columns']!r}, "
        f"{_methods(v)}, {float(v['drift_share'])!r})",
        f"print({cols})",
        _html(v, "drift"),
    )


def prediction_drift(v: V) -> str:
    rep, cols = v["out_report"], v["out_columns"]
    return lines(
        f"{rep}, {cols}, _snapshot = _athena_prediction_drift({v['in_model']}, {v['in_reference']}, {v['in_current']}, {_methods(v)})",
        f"print({rep})",
        _html(v, "prediction_drift"),
    )


def data_quality(v: V) -> str:
    rep, cols = v["out_report"], v["out_columns"]
    return lines(
        f"{rep}, {cols}, _snapshot = _athena_data_quality({v['in_current']}, {v['in_reference']})",
        f"print({cols})",
        _html(v, "data_quality"),
    )


EXPORT: dict[str, Template] = {"evidently_drift": evidently_drift, "prediction_drift": prediction_drift, "data_quality": data_quality}


def endpoint_requests(v: V) -> str:
    from athena.nodes.traffic import request_folder
    return lines(
        f"{v['out_dataset']} = _athena_endpoint_requests({str(request_folder(str(v['model']), check=False))!r}, "
        f"{int(v['last_n'])!r}, {bool(v['include_prediction'])!r})",
        f"print({v['out_dataset']}.tail())",
    )


EXPORT["endpoint_requests"] = endpoint_requests
