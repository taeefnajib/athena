"""Plugin loading: nodes and connectors come from Python entry points.

A plugin is any installed package that declares, in its pyproject.toml:

    [project.entry-points."athena.nodes"]
    my_nodes = "my_package.nodes"          # a module whose import registers @node classes

    [project.entry-points."athena.connectors"]
    my_connectors = "my_package.connectors"  # a module whose import registers @connector classes

Athena's own nodes and connectors are registered the same way (see backend/pyproject.toml).
A plugin that fails to import is reported by GET /api/plugins and skipped; it never stops the app.
"""
from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any

GROUPS = ("athena.nodes", "athena.connectors")
# Imported directly too, so a stale install (entry points not yet regenerated) still works.
BUILTIN_MODULES = ("athena.nodes", "athena.connectors")


@dataclass
class PluginInfo:
    group: str
    name: str
    module: str
    distribution: str | None
    version: str | None
    loaded: bool
    error: str | None = None
    nodes: list[str] | None = None
    connectors: list[str] | None = None


_loaded: list[PluginInfo] = []
_done = False


def _registered() -> tuple[set[str], set[str]]:
    from athena.core.registry import NODE_META
    from athena.connectors.registry import CONNECTOR_META
    return set(NODE_META), set(CONNECTOR_META)


def _load_entry_point(group: str, ep: EntryPoint) -> PluginInfo:
    dist = getattr(ep, "dist", None)
    info = PluginInfo(group, ep.name, ep.value, getattr(dist, "name", None), getattr(dist, "version", None), loaded=False)
    nodes_before, conns_before = _registered()
    try:
        ep.load()
        info.loaded = True
    except Exception as exc:  # a broken plugin must not take Athena down
        info.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
    nodes_after, conns_after = _registered()
    info.nodes = sorted(nodes_after - nodes_before)
    info.connectors = sorted(conns_after - conns_before)
    return info


def load_plugins(force: bool = False) -> list[PluginInfo]:
    """Import built-ins and every installed plugin once per process (API server and each worker)."""
    global _done
    if _done and not force:
        return _loaded
    for mod in BUILTIN_MODULES:
        importlib.import_module(mod)
    seen = set()
    for group in GROUPS:
        for ep in entry_points(group=group):
            if (group, ep.value) in seen or ep.value in BUILTIN_MODULES:
                continue
            seen.add((group, ep.value))
            _loaded.append(_load_entry_point(group, ep))
    _done = True
    return _loaded


def plugin_report() -> list[dict[str, Any]]:
    return [asdict(p) for p in load_plugins()]
