"""The exported script must compute what Athena computed.

Each pipeline is run twice: by Athena's engine, and as the exported Python script (executed in a fresh
namespace). Then every output is compared: DataFrames cell by cell, Series and metric reports value by value.
Together the pipelines cover every node that has an export template (see test_every_template_is_exercised).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

from athena.core.codegen import output_vars, pipeline_to_notebook, pipeline_to_python  # noqa: E402
from athena.core.registry import NODE_META  # noqa: E402
from athena.runtime.engine import run_spec  # noqa: E402
from athena.schemas.pipeline import PipelineSpec  # noqa: E402

BACKEND = Path(__file__).parents[1]
COVERED: set[str] = set()
NONDETERMINISTIC: set[str] = set()  # node types whose outputs can differ between two runs (none today)


class G:
    """A tiny pipeline builder: n(...) adds a node, e(...) wires ports."""

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def n(self, nid: str, ntype: str, **config: Any) -> str:
        self.nodes.append({"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config})
        return nid

    def e(self, src: str, dst: str, sp: int = 0, tp: int = 0) -> None:
        self.edges.append({"id": f"e{len(self.edges)}", "source": src, "target": dst, "source_port": sp, "target_port": tp})

    def model(self, nid: str, ntype: str, split: str, test_ports: tuple[int, int] = (2, 3), metrics_task: str = "classification",
              val: tuple[int, int] | None = None, **config: Any) -> None:
        """A model fed by a split node, plus a Metrics node on the test outputs."""
        self.n(nid, ntype, **config)
        self.e(split, nid, 0, 0)
        self.e(split, nid, 1, 1)
        if val:
            self.e(split, nid, val[0], 2)
            self.e(split, nid, val[1], 3)
        self.n(f"{nid}_m", "metrics", task=metrics_task)
        self.e(nid, f"{nid}_m", 0, 0)
        self.e(split, f"{nid}_m", test_ports[0], 1)
        self.e(split, f"{nid}_m", test_ports[1], 2)

    def spec(self) -> PipelineSpec:
        return PipelineSpec.model_validate({"name": "equivalence", "nodes": self.nodes, "edges": self.edges})


def _compare(where: str, a: Any, b: Any) -> None:
    if isinstance(a, pd.DataFrame):
        assert isinstance(b, pd.DataFrame), f"{where}: export produced {type(b).__name__}"
        pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=False, rtol=1e-6, obj=where)
    elif isinstance(a, pd.Series):
        pd.testing.assert_series_equal(a, pd.Series(b, index=a.index), check_dtype=False, check_names=False,
                                       check_exact=False, rtol=1e-6, obj=where)
    elif isinstance(a, dict) and all(isinstance(v, (int, float)) for v in a.values()):
        assert isinstance(b, dict), f"{where}: export produced {type(b).__name__}"
        for k, v in a.items():
            assert k in b, f"{where}: export lacks {k!r}"
            assert b[k] == pytest.approx(v, rel=1e-6, abs=1e-9), f"{where}[{k}]: Athena {v} vs export {b[k]}"


def run_both(spec: PipelineSpec, tmp: Path, skip: set[str] | None = None) -> dict[str, Any]:
    """Run with Athena and as an exported script in ``tmp``; compare all outputs. Returns the script namespace."""
    skip = skip or set()
    artifacts: dict[tuple[str, int], Any] = {}
    events: list[dict] = []
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        status = run_spec(spec, "eq", events.append, lambda: False, tmp / "cache", artifacts_out=artifacts)
        errors = [e["error"]["message"] for e in events if e["type"] == "node_finish" and e["status"] == "error"]
        assert status == "completed", errors
        code = pipeline_to_python(spec)
        assert "Not exported" not in code, [ln for ln in code.splitlines() if "Not exported" in ln]
        (tmp / "pipeline.py").write_text(code, encoding="utf-8")
        ns: dict[str, Any] = {"__name__": "__main__"}
        exec(compile(code, str(tmp / "pipeline.py"), "exec"), ns)  # noqa: S102 - the export under test
    finally:
        os.chdir(cwd)
    for node in spec.nodes:
        COVERED.add(node.type)
        if node.id in skip or node.type in NONDETERMINISTIC:
            continue
        for port, var in enumerate(output_vars(node.id, node.type)):
            if (node.id, port) in artifacts:
                assert var in ns, f"export never defined {var} ({node.type})"
                _compare(f"{node.id}:{node.type}.{var}", artifacts[(node.id, port)], ns[var])
    return ns


def test_classification_with_every_classifier(tmp_path: Path):
    g = G()
    g.n("csv", "csv_loader", path=str(BACKEND / "data.csv"))
    g.n("imp", "imputer", strategy="median"); g.e("csv", "imp")
    g.n("sc", "scaler", method="RobustScaler"); g.e("imp", "sc")
    g.n("tt", "train_test", stratify=True); g.e("sc", "tt")
    for nid, ntype, cfg in [("rf", "rf", {"n_estimators": 30}), ("lr", "log_reg", {}), ("dt", "dtree", {}), ("xg", "xgb", {"n_estimators": 30}),
                            ("kn", "knn", {}), ("gnb", "nb", {}), ("ml", "mlp", {"layers": "16", "epochs": 200}), ("sv", "svm", {}),
                            ("lg", "lgbm", {"n_estimators": 50}), ("cb", "catboost", {"n_estimators": 50})]:
        g.model(nid, ntype, "tt", **cfg)
    for nid, ntype in [("cm", "conf_matrix"), ("roc", "roc_curve"), ("dbg", "debugger")]:
        g.n(nid, ntype); g.e("rf", nid, 0, 0); g.e("tt", nid, 2, 1); g.e("tt", nid, 3, 2)
    g.n("fi", "feat_imp_viz"); g.e("rf", "fi")
    g.n("shp", "shap", n_samples=20); g.e("rf", "shp"); g.e("tt", "shp", 2, 1)
    g.n("vote", "voting", voting="soft"); g.e("rf", "vote", 0, 0); g.e("lr", "vote", 0, 1); g.e("dt", "vote", 0, 2)
    g.n("stk", "stacking"); g.e("rf", "stk", 0, 0); g.e("lr", "stk", 0, 1); g.e("tt", "stk", 0, 5); g.e("tt", "stk", 1, 6)
    for nid in ("vote", "stk"):
        g.n(f"{nid}_m", "metrics"); g.e(nid, f"{nid}_m", 0, 0); g.e("tt", f"{nid}_m", 2, 1); g.e("tt", f"{nid}_m", 3, 2)
    g.n("pw", "pipeline_wrap"); g.e("sc", "pw", 0, 0); g.e("rf", "pw", 0, 1)
    ns = run_both(g.spec(), tmp_path)
    assert (tmp_path / "cm_confusion_matrix.png").exists() and (tmp_path / "shp_shap.png").exists()
    assert ns["report_rf_m"]["accuracy"] > 0.8


def test_regression_with_every_regressor_and_tuning(tmp_path: Path):
    g = G()
    g.n("csv", "csv_loader", path=str(BACKEND / "regression_data.csv"))
    g.n("imp", "imputer", strategy="knn"); g.e("csv", "imp")
    g.n("fg", "feat_gen", degree=2); g.e("imp", "fg")
    g.n("tvt", "train_val_test"); g.e("fg", "tvt")
    for nid, ntype, cfg in [("lin", "lin_reg", {}), ("rid", "ridge", {}), ("las", "lasso", {"alpha": 0.1}), ("rfr", "rf_reg", {"n_estimators": 30}),
                            ("xgr", "xgb_reg", {"n_estimators": 30}), ("dtr", "dtree_reg", {}), ("svr", "svr", {}), ("knr", "knn_reg", {}),
                            ("mlr", "mlp_reg", {"layers": "16", "epochs": 300}), ("gbr", "gb_reg", {"n_estimators": 30}),
                            ("cbr", "catboost_reg", {"n_estimators": 60})]:
        g.model(nid, ntype, "tvt", test_ports=(4, 5), metrics_task="regression", **cfg)
    g.model("lgr", "lgbm_reg", "tvt", test_ports=(4, 5), metrics_task="regression", val=(2, 3),
            n_estimators=500, early_stopping_rounds=10)
    g.n("hp", "hp_tune", method="Random", scoring="r2", n_iter=4, cv=3, n_jobs=1,
        params=[{"key": "max_depth", "values": "2,4,6"}, {"key": "min_samples_split", "values": "2-6"}])
    g.model("tuned", "dtree_reg", "tvt", test_ports=(4, 5), metrics_task="regression")
    g.e("hp", "tuned", 0, 4)
    g.n("res", "residual"); g.e("lin", "res", 0, 0); g.e("tvt", "res", 4, 1); g.e("tvt", "res", 5, 2)
    ns = run_both(g.spec(), tmp_path)
    assert ns["report_lin_m"]["r2"] > 0.5


def test_text_pipeline(tmp_path: Path):
    g = G()
    g.n("csv", "csv_loader", path=str(BACKEND / "nlp_data.csv"))
    g.n("vec", "tfidf", col="text", max_features=200); g.e("csv", "vec")
    g.n("tt", "train_test"); g.e("vec", "tt")
    g.model("mnb", "nb", "tt", variant="MultinomialNB")
    g.n("hp", "hp_tune", method="Optuna", scoring="accuracy", n_iter=4, cv=3, n_jobs=1, params=[{"key": "C", "values": "0.01,0.1,1,10"}])
    g.model("opt", "log_reg", "tt")
    g.e("hp", "opt", 0, 4)
    run_both(g.spec(), tmp_path)


def test_data_preparation_nodes(tmp_path: Path):
    rng = np.random.default_rng(3)
    n = 240
    base = pd.DataFrame({
        "id": range(n), "age": rng.integers(18, 80, n).astype(float), "income": rng.normal(50, 15, n).round(2),
        "city": rng.choice(["dhaka", "berlin", "lima"], n), "joined": pd.date_range("2024-01-01", periods=n, freq="D").astype(str),
        "full_name": [f"ana {i}" for i in range(n)], "target": rng.integers(0, 2, n),
    })
    base.loc[::17, "income"] = np.nan
    base.loc[5] = base.loc[4]  # a duplicate row
    base.loc[[3, 9], "income"] = [500.0, -300.0]  # outliers
    base.to_json(tmp_path / "people.json", orient="records")
    base.to_excel(tmp_path / "people.xlsx", sheet_name="Sheet1", index=False)
    pd.DataFrame({"id": range(n), "score": rng.normal(size=n).round(4)}).to_parquet(tmp_path / "scores.parquet")

    g = G()
    g.n("js", "json_loader", path=str(tmp_path / "people.json"))
    g.n("xl", "excel_loader", path=str(tmp_path / "people.xlsx"))
    g.n("pq", "parquet_loader", path=str(tmp_path / "scores.parquet"))
    g.n("man", "manual_input", columns="city, region", data="dhaka, south asia\nberlin, europe\nlima, south america")
    g.n("syn", "synth_data", rows=200, features=5)
    g.n("mg", "data_merge", on="id", how="left"); g.e("js", "mg", 0, 0); g.e("pq", "mg", 0, 1)
    g.n("mg2", "data_merge", on="city", how="left"); g.e("mg", "mg2", 0, 0); g.e("man", "mg2", 0, 1)
    g.n("dup", "dup_remover"); g.e("mg2", "dup")
    g.n("o1", "outlier", method="IQR", action="clip", cols="income"); g.e("dup", "o1")
    g.n("o2", "outlier", method="Z-Score", action="remove", threshold=3.0); g.e("dup", "o2")
    g.n("o3", "outlier", method="Isolation Forest", action="flag", cols="id", col_mode="exclude"); g.e("dup", "o3")
    g.n("imp", "imputer", strategy="constant", fill_value="0"); g.e("o1", "imp")
    g.n("ren", "col_rename", mappings=[{"key": "score", "values": "credit_score"}]); g.e("imp", "ren")
    g.n("tc", "type_conv", rules="age: int\njoined: datetime"); g.e("ren", "tc")
    g.n("val", "validator", schema='{"age": "int", "city": "str", "missing": "float"}'); g.e("tc", "val")
    g.n("df", "date_feat", col="joined", features="year,month,weekday,is_weekend,quarter"); g.e("val", "df")
    g.n("ss", "str_split", col="full_name", sep="space", prefix="name"); g.e("df", "ss")
    g.n("le", "label_enc", cols="region"); g.e("ss", "le")
    g.n("oh", "ohe", cols="city", drop=True); g.e("le", "oh")
    g.n("sel", "col_selector", mode="exclude", cols="joined, full_name, name_0, name_1"); g.e("oh", "sel")
    g.n("sql", "duckdb_sql", query="SELECT a.*, b.cnt FROM in1 a JOIN (SELECT target, COUNT(*) AS cnt FROM in2 GROUP BY 1) b USING (target) ORDER BY id")
    g.e("sel", "sql", 0, 0); g.e("sel", "sql", 0, 1)
    g.n("cc", "custom_code", code="df['income_k'] = df['income'] / 1000\nreturn df"); g.e("sql", "cc")
    g.n("smp", "data_sample", frac=0.5, random_state=1); g.e("cc", "smp")
    g.n("fs", "feat_imp_sel", k=5); g.e("cc", "fs")
    g.n("pca", "pca", n_components=3); g.e("cc", "pca")
    g.n("sm", "smote"); g.e("syn", "sm")
    g.n("us", "undersample"); g.e("syn", "us")
    g.n("us2", "undersample", strategy="tomek"); g.e("syn", "us2")
    g.n("ov", "oversample"); g.e("syn", "ov")
    g.n("cw", "class_weight"); g.e("syn", "cw")
    g.n("cv", "cv_split", k=4, fold_index=1); g.e("syn", "cv")
    g.n("xy", "dataset_to_xy"); g.e("syn", "xy")
    g.n("back", "xy_to_dataset"); g.e("xy", "back", 0, 0); g.e("xy", "back", 1, 1)
    g.n("info", "df_info"); g.e("cc", "info")
    for i, chart in enumerate(["Histogram", "Bar", "Scatter", "Box", "Pie", "Heatmap", "Line"]):
        g.n(f"viz{i}", "data_viz", chart_type=chart, x_col="city_lima" if chart == "Bar" else "", y_col="income" if chart == "Box" else "")
        g.e("cc", f"viz{i}")
    g.n("corr", "corr_check"); g.e("cc", "corr")
    g.n("corr2", "corr_check", mode="Pairwise", col1="age", col2="income"); g.e("cc", "corr2")
    g.n("cd", "class_dist"); g.e("cc", "cd")
    g.n("drift", "drift_detect"); g.e("sm", "drift", 0, 0); g.e("syn", "drift", 0, 1)
    g.n("psi", "drift_detect", method="PSI"); g.e("ov", "psi", 0, 0); g.e("syn", "psi", 0, 1)
    g.n("out", "csv_export", path=str(tmp_path / "out" / "clean.csv")); g.e("cc", "out")
    run_both(g.spec(), tmp_path)
    assert (tmp_path / "out" / "clean.csv").exists()


def test_deployment_nodes(tmp_path: Path):
    g = G()
    g.n("syn", "synth_data", rows=300, features=6)
    g.n("sc", "scaler"); g.e("syn", "sc")
    g.n("ts", "transformer_save", path=str(tmp_path / "scaler.pkl")); g.e("sc", "ts", 1, 0); g.e("sc", "ts", 0, 1)
    g.n("tt", "train_test"); g.e("ts", "tt")
    g.model("rf", "rf", "tt", n_estimators=20)
    g.n("save", "model_saver", path=str(tmp_path / "model.joblib")); g.e("rf", "save")
    g.n("pred", "predict", proba=True); g.e("rf", "pred", 0, 0); g.e("tt", "pred", 2, 1)
    g.n("pp", "pred_print"); g.e("pred", "pp")
    g.n("perf", "perf_tracker"); g.e("rf", "perf", 0, 0); g.e("syn", "perf", 0, 1)
    g.n("rep", "report_gen", path=str(tmp_path / "report.html")); g.e("rf_m", "rep")
    run_both(g.spec(), tmp_path)
    # loading what the first pipeline saved
    g2 = G()
    g2.n("syn", "synth_data", rows=300, features=6)
    g2.n("drop", "col_selector", mode="exclude", cols="target"); g2.e("syn", "drop")
    g2.n("tl", "transformer_load", path=str(tmp_path / "scaler.pkl"), cols="feature_0,feature_1,feature_2,feature_3,feature_4,feature_5")
    g2.e("drop", "tl")
    g2.n("ml", "model_loader", path=str(tmp_path / "model.joblib")); g2.e("tl", "ml")
    run_both(g2.spec(), tmp_path, skip={"tl"})  # transformer_load reads from Athena's data dir at runtime


def test_every_template_is_exercised():
    """Runs last: every node type with an export template appeared in an equivalence pipeline above,
    except the ones that need external services or an extra (tested in their own modules)."""
    elsewhere = {"db_connector", "storage_loader", "automl", "mlflow_register", "mlflow_load", "transformer_load"}
    templated = {t for t, m in NODE_META.items() if m.code is not None and not t.startswith("test_plugin")}
    missing = templated - COVERED - elsewhere
    assert not missing, f"no equivalence test for: {sorted(missing)}"


def test_notebook_export_is_valid(tmp_path: Path):
    import json
    nb = json.loads(pipeline_to_notebook(PipelineSpec.model_validate({"name": "nb", "nodes": [
        {"id": "s", "type": "synth_data", "position": {"x": 0, "y": 0}, "config": {"rows": 50, "features": 3}},
        {"id": "tt", "type": "train_test", "position": {"x": 0, "y": 0}, "config": {}},
    ], "edges": [{"id": "e", "source": "s", "target": "tt"}]})))
    assert nb["nbformat"] == 4
    code = "\n".join(c["source"] for c in nb["cells"] if c["cell_type"] == "code")
    ns: dict[str, Any] = {}
    exec(compile(code, "nb", "exec"), ns)  # noqa: S102
    assert len(ns["X_train_tt"]) == 40
    assert [c["cell_type"] for c in nb["cells"]][:2] == ["markdown", "code"]
