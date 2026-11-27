"""Export templates: statsmodels OLS and Logit. The estimator wrappers (``_StatsOLS``, ``_StatsLogit``) are
copied verbatim into the script by codegen, so the exported model behaves exactly like Athena's."""
from __future__ import annotations

from typing import Any

from athena.nodes.export.common import Template, lines

V = dict[str, Any]


def sm_ols(v: V) -> str:
    m, coef = v["out_model"], v["out_coefficients"]
    return lines(
        f"{m} = _StatsOLS(add_constant={bool(v['add_constant'])}, cov_type={v['cov_type']!r}).fit({v['in_X_train']}, {v['in_y_train']})",
        f"print({m}.summary())",
        f"{coef} = {m}.coef_table()",
    )


def sm_logit(v: V) -> str:
    m, coef = v["out_model"], v["out_coefficients"]
    return lines(
        f"{m} = _StatsLogit(add_constant={bool(v['add_constant'])}, cov_type={v['cov_type']!r}, max_iter={int(v['max_iter'])})"
        f".fit({v['in_X_train']}, {v['in_y_train']})",
        f"print({m}.summary())",
        f"{coef} = {m}.coef_table()",
    )


EXPORT: dict[str, Template] = {"sm_ols": sm_ols, "sm_logit": sm_logit}
