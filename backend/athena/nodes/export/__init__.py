"""Export templates for the built-in nodes, keyed by node type. Node definitions pick theirs with
``code=EXPORT["<type>"]`` so the export decision stays declared on the node itself.

Templates are pure functions of the node's values (see athena/core/codegen.py for what they receive) and
mirror the node's handler: the exported script must compute what Athena computed.
"""
from athena.nodes.export import data, evaluate, io, models
from athena.nodes.export.common import Template

EXPORT: dict[str, Template] = {**data.EXPORT, **models.EXPORT, **evaluate.EXPORT, **io.EXPORT}

__all__ = ["EXPORT", "Template"]
