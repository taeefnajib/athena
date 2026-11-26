"""Every registered node must be internally consistent: this is what replaced keeping two registries in sync."""
import json

import pytest

import athena.nodes  # noqa: F401
from athena.core.registry import CATEGORIES, NODE_META, NODE_REGISTRY
from athena.sdk import config_defaults, node_spec, render_code

ALL = sorted(NODE_META)


def test_every_handler_has_metadata():
    assert set(NODE_REGISTRY) == set(NODE_META)
    assert len(ALL) >= 83


@pytest.mark.parametrize("node_type", ALL)
def test_spec_is_consistent(node_type: str):
    meta = NODE_META[node_type]
    spec = node_spec(meta)
    json.dumps(spec)  # served as JSON

    assert meta.category in CATEGORIES
    assert meta.label and meta.description
    for ports in (meta.inputs, meta.outputs):
        names = [p.name for p in ports]
        assert len(names) == len(set(names)), f"duplicate port names: {names}"

    model_fields = meta.config.model_fields if meta.config else {}
    dangling = set(meta.fields) - set(model_fields)
    assert not dangling, f"UI hints for fields that aren't in Config: {dangling}"

    for f in spec["config"]:
        if f["type"] == "select":
            assert f["options"], f"{f['id']}: select without options"
            assert str(f["default"]) in [str(o) for o in f["options"]], f"{f['id']}: default not among options"
        if f["type"] in ("hp_params", "col_map"):
            assert isinstance(f["default"], list), f"{f['id']}: {f['type']} default must be a list"
        if f["type"] == "number":
            assert isinstance(f["default"], (int, float)), f"{f['id']}: number field with non-numeric default"

    if not meta.available:
        assert meta.unavailable_reason


@pytest.mark.parametrize("node_type", [t for t in ALL if NODE_META[t].code])
def test_export_template_fills_from_defaults(node_type: str):
    """A node saved with an empty config must still export (no 'template error')."""
    meta = NODE_META[node_type]
    assert meta.code is not None
    out = render_code(meta, {"id": "n1", "var": "n1", "src": "n0", "src_model": "n0", "src_test": "n0", **config_defaults(meta)})
    assert "n1" in out


def test_export_is_an_explicit_decision():
    for t in ALL:
        meta = NODE_META[t]
        assert (meta.code is None) != (meta.export_note is None), t
