"""Third-party packages add nodes through the athena.nodes entry point; broken plugins are reported, not fatal."""
from importlib.metadata import EntryPoint

import pandas as pd

import athena.plugins as plugins
from athena.core.handler import ExecutionContext
from athena.core.registry import NODE_META, get_handler
from athena.sdk import node_spec


def _fake_entry_points(group: str):
    if group == "athena.nodes":
        return [
            EntryPoint(name="builtin", value="athena.nodes", group=group),
            EntryPoint(name="good", value="tests.plugin_fixtures.good_plugin", group=group),
            EntryPoint(name="broken", value="tests.plugin_fixtures.broken_plugin", group=group),
        ]
    return []


def test_plugins_register_nodes_and_failures_are_reported(monkeypatch):
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points)
    monkeypatch.setattr(plugins, "_loaded", [])
    report = {p.name: p for p in plugins.load_plugins(force=True)}

    assert set(report) == {"good", "broken"}  # built-ins are imported directly, not reported as plugins
    assert report["good"].loaded and report["good"].nodes == ["test_plugin_double"]
    assert not report["broken"].loaded and "isn't installed" in report["broken"].error

    spec = node_spec(NODE_META["test_plugin_double"])
    assert spec["category"] == "community" and spec["exportable"]

    import structlog
    ctx = ExecutionContext(node_id="p1", node_type="test_plugin_double", config={"col": "x"},
                           inputs=[pd.DataFrame({"x": [1, 2]})], run_id="r", cache_dir=None,  # type: ignore[arg-type]
                           logger=structlog.get_logger())
    assert get_handler("test_plugin_double")(ctx).outputs[0]["x"].tolist() == [2, 4]
