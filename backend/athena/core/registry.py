"""Registered nodes. Populated by ``@node`` (athena.sdk) when node modules and plugins import."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from athena.sdk.node import NodeMeta

# type -> handler instance (callable as handler(ctx) -> HandlerResult)
NODE_REGISTRY: dict[str, Any] = {}
# type -> metadata (ports, config, UI hints, export template)
NODE_META: dict[str, NodeMeta] = {}

# Categories the built-in nodes use. Plugins may introduce new ones with register_category().
CATEGORIES: dict[str, dict[str, str]] = {
    "data":     {"label": "Data Input",       "icon": "⊞"},
    "quality":  {"label": "Data Quality",     "icon": "✦"},
    "feature":  {"label": "Feature Eng.",     "icon": "◈"},
    "balance":  {"label": "Data Balancing",   "icon": "⊜"},
    "split":    {"label": "Data Split",       "icon": "⋈"},
    "model":    {"label": "Models",           "icon": "◉"},
    "advanced": {"label": "Advanced ML",      "icon": "◎"},
    "ensemble": {"label": "Ensemble",         "icon": "⊕"},
    "eval":     {"label": "Evaluation",       "icon": "◇"},
    "interp":   {"label": "Interpretability", "icon": "◑"},
    "deploy":   {"label": "Deployment",       "icon": "⊳"},
    "monitor":  {"label": "Monitoring",       "icon": "◐"},
}


def register_category(cat_id: str, label: str, icon: str = "●") -> None:
    CATEGORIES.setdefault(cat_id, {"label": label, "icon": icon})


def register_node(meta: NodeMeta, handler: Any) -> None:
    if meta.type in NODE_REGISTRY:
        raise ValueError(f"Duplicate node type: {meta.type}")
    if meta.category not in CATEGORIES:
        raise ValueError(f"node {meta.type!r}: unknown category {meta.category!r} (register_category first)")
    NODE_REGISTRY[meta.type] = handler
    NODE_META[meta.type] = meta


def get_handler(node_type: str) -> Any:
    if node_type not in NODE_REGISTRY:
        raise KeyError(f"Unknown node type: {node_type!r}")
    return NODE_REGISTRY[node_type]


def get_meta(node_type: str) -> NodeMeta:
    if node_type not in NODE_META:
        raise KeyError(f"Unknown node type: {node_type!r}")
    return NODE_META[node_type]

