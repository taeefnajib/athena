"""Optuna as a search method of the HP Tuning Config node."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import structlog

pytest.importorskip("optuna")

from athena.core.handler import ExecutionContext  # noqa: E402
from athena.nodes.advanced import HpTuneHandler  # noqa: E402
from athena.nodes.model import RfHandler, _optuna_space  # noqa: E402


def _ctx(node_type: str, config: dict, inputs: list) -> ExecutionContext:
    return ExecutionContext(node_id="n", node_type=node_type, config=config, inputs=inputs, run_id="r",
                            cache_dir=Path("."), logger=structlog.get_logger())


def test_search_space_rules():
    assert _optuna_space(list(range(10, 201))) == ("int", (10, 200))
    assert _optuna_space([0.001, 0.01, 0.1, 1.0]) == ("float", (0.001, 1.0, True))
    assert _optuna_space([2, 4, 8]) == ("categorical", [2, 4, 8])
    assert _optuna_space(["gini", "entropy"]) == ("categorical", ["gini", "entropy"])


def test_optuna_tunes_a_random_forest():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(200, 4)), columns=list("abcd"))
    y = (X["a"] - X["c"] > 0).astype(int)
    hp = HpTuneHandler()(_ctx("hp_tune", {"method": "Optuna", "n_iter": 6, "cv": 3, "n_jobs": 1, "params": [
        {"key": "n_estimators", "values": "10-80"}, {"key": "max_depth", "values": "2,4,8"}]}, [])).outputs[0]
    assert hp["method"] == "Optuna"
    result = RfHandler()(_ctx("rf", {"n_estimators": 10}, [X, y, None, None, hp]))
    model = result.outputs[0]
    assert 10 <= model.n_estimators <= 80 and model.max_depth in (2, 4, 8)
    assert result.preview.summary.startswith("Optuna (6 trials) best CV accuracy")
