import pytest
from pathlib import Path
from unittest.mock import MagicMock
from athena.nodes.data import CsvLoaderHandler
from athena.core.handler import ExecutionContext
import structlog


def _ctx(tmp_path: Path, config: dict) -> ExecutionContext:
    return ExecutionContext(
        node_id="n1",
        node_type="csv_loader",
        config=config,
        inputs=[],
        run_id="test-run",
        cache_dir=tmp_path,
        logger=structlog.get_logger(),
    )


IRIS_CSV = Path(__file__).parent.parent / "fixtures" / "data" / "iris.csv"


def test_csv_loader_loads_iris(tmp_path: Path):
    handler = CsvLoaderHandler()
    ctx = _ctx(tmp_path, {"path": str(IRIS_CSV), "sep": ",", "header": True, "encoding": "utf-8"})
    result = handler(ctx)
    df = result.outputs[0]
    assert len(df) == 150
    assert len(df.columns) == 5
    assert result.preview is not None
    assert result.preview.kind == "dataframe"
    assert result.metrics["rows"] == 150.0


def test_csv_loader_file_not_found(tmp_path: Path):
    handler = CsvLoaderHandler()
    ctx = _ctx(tmp_path, {"path": "/nonexistent/file.csv", "sep": ",", "header": True, "encoding": "utf-8"})
    with pytest.raises(ValueError, match="not found"):
        handler(ctx)


def test_csv_loader_tab_separator(tmp_path: Path):
    tsv = tmp_path / "data.tsv"
    tsv.write_text("a\tb\tc\n1\t2\t3\n4\t5\t6\n", encoding="utf-8")
    handler = CsvLoaderHandler()
    ctx = _ctx(tmp_path, {"path": str(tsv), "sep": "\\t", "header": True, "encoding": "utf-8"})
    result = handler(ctx)
    df = result.outputs[0]
    assert list(df.columns) == ["a", "b", "c"]
    assert len(df) == 2


def test_csv_loader_preview_capped(tmp_path: Path):
    import pandas as pd
    large = tmp_path / "large.csv"
    pd.DataFrame({"x": range(200), "y": range(200)}).to_csv(large, index=False)
    handler = CsvLoaderHandler()
    ctx = _ctx(tmp_path, {"path": str(large), "sep": ",", "header": True, "encoding": "utf-8"})
    result = handler(ctx)
    assert result.preview.shape == (200, 2)
    assert len(result.preview.rows) == 50  # capped at 50
