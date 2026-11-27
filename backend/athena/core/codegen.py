"""Pipeline -> standalone Python (script or notebook). Pure functions of the PipelineSpec.

Every node output port becomes a variable (``df_n1``, ``model_n4``, ``X_train_n3`` …); a node's template
receives its inputs as the variables of whatever is connected to each port, so exports follow the real
graph rather than assuming a fixed layout. Template values:

    id, var, label             the node's id, a Python-safe version of it, and its label
    in_<port>, out_<port>      variable names for each input / output port ("None" if not connected)
    <config field>             every config field, with defaults filled in

Imports in templates (at column 0) are collected, de-duplicated and moved to the top of the script.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from athena.core.dag import topo_sort
from athena.core.export_helpers import helpers_for
from athena.core.registry import NODE_META
from athena.plugins import load_plugins
from athena.schemas.pipeline import PipelineSpec
from athena.sdk import config_defaults, render_code

load_plugins()

TYPE_PREFIX = {
    "dataset": "df", "model": "model", "X_train": "X_train", "y_train": "y_train", "X_val": "X_val", "y_val": "y_val",
    "X_test": "X_test", "y_test": "y_test", "report": "report", "plot": "fig", "predictions": "df_pred",
    "transformer": "transformer", "hpconfig": "hp", "pipeline": "pipeline", "outliers": "outliers",
}
IMPORT_RE = re.compile(r"^(import \S|from \S+ import \S)")


def safe(name: str) -> str:
    s = re.sub(r"\W", "_", name)
    return s if s and not s[0].isdigit() else f"n_{s}"


@dataclass
class Section:
    node_id: str
    label: str
    description: str
    code: str                      # body without imports
    imports: list[str] = field(default_factory=list)
    exported: bool = True


def output_vars(node_id: str, node_type: str) -> list[str]:
    meta = NODE_META.get(node_type)
    if meta is None:
        return []
    var = safe(node_id)
    names = [f"{TYPE_PREFIX.get(p.type, safe(p.name))}_{var}" for p in meta.outputs]
    if len(set(names)) < len(names):  # two outputs of the same type: use the port names
        names = [f"{safe(p.name)}_{var}" for p in meta.outputs]
    return names


def _split_imports(code: str) -> tuple[list[str], str]:
    imports, body = [], []
    for line in code.splitlines():
        (imports if IMPORT_RE.match(line) else body).append(line)
    return imports, "\n".join(body).strip("\n")


def build_sections(spec: PipelineSpec) -> list[Section]:
    try:
        order = topo_sort([{"id": n.id} for n in spec.nodes], [{"source": e.source, "target": e.target} for e in spec.edges])
    except ValueError:
        order = [n.id for n in spec.nodes]
    outs = {n.id: output_vars(n.id, n.type) for n in spec.nodes}
    sections: list[Section] = []
    for node_id in order:
        node = spec.node(node_id)
        meta = NODE_META.get(node.type)
        if meta is None:
            sections.append(Section(node_id, node.type, "", f"# Unknown node type {node.type!r}: not exported.", exported=False))
            continue
        if meta.code is None:
            sections.append(Section(node_id, meta.label, meta.description, f"# Not exported: {meta.export_note}", exported=False))
            continue
        inputs: dict[str, str] = {}
        missing: list[str] = []
        for i, port in enumerate(meta.inputs):
            edge = next((e for e in spec.edges if e.target == node_id and e.target_port == i), None)
            src_vars = outs.get(edge.source, []) if edge else []
            var = src_vars[edge.source_port] if edge and edge.source_port < len(src_vars) else None
            inputs[f"in_{safe(port.name)}"] = var or "None"
            if var is None and not port.optional:
                missing.append(port.name)
        if missing:
            sections.append(Section(node_id, meta.label, meta.description,
                                    f"# Not exported: input {', '.join(repr(m) for m in missing)} isn't connected.", exported=False))
            continue
        values = {**config_defaults(meta), **node.config, **inputs,
                  **{f"out_{safe(p.name)}": v for p, v in zip(meta.outputs, outs[node_id])},
                  "id": node_id, "var": safe(node_id), "label": meta.label}
        try:
            imports, body = _split_imports(render_code(meta, values))
        except (KeyError, IndexError, ValueError) as exc:
            sections.append(Section(node_id, meta.label, meta.description, f"# Export failed: {exc}", exported=False))
            continue
        sections.append(Section(node_id, meta.label, meta.description, body, imports))
    return sections


def _header(sections: list[Section]) -> tuple[list[str], list[str]]:
    body = "\n".join(s.code for s in sections)
    helper_src, helper_imports = helpers_for(body)
    imports: list[str] = []
    for line in [i for s in sections for i in s.imports] + helper_imports:
        if line not in imports:
            imports.append(line)
    return imports, helper_src


def pipeline_to_python(spec: PipelineSpec) -> str:
    sections = build_sections(spec)
    imports, helpers = _header(sections)
    skipped = [s for s in sections if not s.exported]
    out = ["# Generated by Athena", f"# Pipeline: {spec.name}"]
    if skipped:
        out.append(f"# Note: {len(skipped)} node(s) could not be exported; see the comments below.")
    out.append("")
    out += imports
    if helpers:
        out += ["", ""] + ["\n\n\n".join(h.rstrip() for h in helpers)]
    for s in sections:
        out += ["", f"# --- Node {s.node_id}: {s.label} ---", s.code]
    return "\n".join(out).rstrip() + "\n"


def pipeline_to_notebook(spec: PipelineSpec) -> str:
    """Same content as the script: one markdown + one code cell per node (nbformat v4 JSON)."""
    sections = build_sections(spec)
    imports, helpers = _header(sections)

    def md(text: str) -> dict:
        return {"cell_type": "markdown", "metadata": {}, "source": text}

    def code(text: str) -> dict:
        return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text}

    cells = [md(f"# {spec.name}\n\nGenerated by Athena. Runs without Athena: only the libraries imported below are needed.")]
    cells.append(code("\n".join(imports) + ("\n\n\n" + "\n\n\n".join(h.rstrip() for h in helpers) if helpers else "")))
    for s in sections:
        cells.append(md(f"### {s.label} (`{s.node_id}`)\n\n{s.description}"))
        cells.append(code(s.code))
    nb = {"cells": cells, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(nb, indent=1)


def pipeline_to_json(spec: PipelineSpec) -> str:
    return json.dumps(spec.model_dump(), indent=2)
