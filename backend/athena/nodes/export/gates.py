"""Export templates: Quality Gate and Fairness Check. They call the same helpers as the nodes
(``_athena_check_rules``, ``_athena_fairness``), copied verbatim into the script."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]


def quality_gate(v: V) -> str:
    reports = ", ".join(v[k] for k in ("in_report", "in_report_2", "in_report_3"))
    rep, model = v["out_report"], v["out_model"]
    stop = v["on_fail"] == "stop"
    return lines(
        f"_gate = _athena_check_rules([{reports}], {v['rules']!r})",
        "for _rule, _metric, _value, _ok in _gate:\n    print('PASS' if _ok else 'FAIL', _rule, f'(got {_value:.4g})')",
        f"{rep} = {{'passed': float(all(r[3] for r in _gate)), 'rules_passed': float(sum(r[3] for r in _gate)), 'rules_total': float(len(_gate))}}",
        (f"if not {rep}['passed']:\n    raise SystemExit('Quality gate failed: ' + '; '.join(f'{{r[0]}} (got {{r[2]:.4g}})' for r in _gate if not r[3]))"
         if stop else ""),
        f"{model} = {v['in_model']}",
    )


def fairness_check(v: V) -> str:
    rep = v["out_report"]
    return lines(
        f"{rep}, _groups = _athena_fairness({v['in_model']}, {v['in_X_test']}, {v['in_y_test']}, {v['sensitive_col'].strip()!r}, {v['positive_class']!r})",
        "for _g in _groups:\n    print(_g)",
        f"print({rep})",
    )


EXPORT: dict[str, Template] = {"quality_gate": quality_gate, "fairness_check": fairness_check}
