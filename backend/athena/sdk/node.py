"""The node SDK: one Python definition per node is the single source of truth.

A node declares its identity, typed ports, a Pydantic ``Config`` and optional UI hints with
``@node(...)``. ``GET /api/nodes`` serves :func:`node_spec` for every registered node, and the
frontend builds its library and inspector forms from that, so nothing is defined twice.
"""
from __future__ import annotations

import types
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypeVar

from pydantic import BaseModel, SecretStr

Widget = Literal["text", "number", "select", "toggle", "textarea", "file", "hp_params", "col_map", "password", "connection"]


@dataclass(frozen=True)
class Port:
    """A typed input or output. ``type`` decides which ports may connect (see lib/validation.ts)."""

    name: str
    type: str


@dataclass(frozen=True)
class FieldUI:
    """How one ``Config`` field appears in the inspector. Everything is optional: labels default
    to the field's ``title`` or its name, widgets and options are inferred from the type."""

    label: str | None = None
    widget: Widget | None = None
    options: tuple[str, ...] | None = None
    accept: str | None = None
    mono: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    connector: str | None = None
    """For widget="connection": which connector type's saved connections to offer."""
    help: str | None = None
    empty_label: str | None = None
    """For widget="connection": what the empty choice means, e.g. "Local MLflow store"."""


def ui(
    label: str | None = None,
    *,
    widget: Widget | None = None,
    options: list[str] | tuple[str, ...] | None = None,
    accept: str | None = None,
    mono: bool = False,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    connector: str | None = None,
    help: str | None = None,
    empty_label: str | None = None,
) -> FieldUI:
    """Shorthand for :class:`FieldUI`: ``ui("Estimators")``, ``ui("Code", widget="textarea", mono=True)``,
    ``ui("Connection", widget="connection", connector="sql")``."""
    return FieldUI(label, widget, tuple(options) if options is not None else None, accept, mono, min, max, step, connector, help, empty_label)


@dataclass(frozen=True)
class NodeMeta:
    type: str
    label: str
    category: str
    description: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    config: type[BaseModel] | None
    fields: dict[str, FieldUI] = field(default_factory=dict)
    code: str | Callable[[dict[str, Any]], str] | None = None
    """Export template: a str.format template, or a function of the same values returning code.
    Values: id, var, src, src_model, src_test, plus every config field (defaults filled in)."""
    export_note: str | None = None
    """Why the node has no export template. Exactly one of ``code`` / ``export_note`` is set."""
    available: bool = True
    unavailable_reason: str | None = None
    runtime: str = "python"


class _EmptyConfig(BaseModel):
    pass


H = TypeVar("H", bound=type)


def node(
    type: str,
    *,
    label: str,
    category: str,
    description: str,
    inputs: list[Port] | tuple[Port, ...] = (),
    outputs: list[Port] | tuple[Port, ...] = (),
    fields: dict[str, FieldUI] | None = None,
    code: str | Callable[[dict[str, Any]], str] | None = None,
    export_note: str | None = None,
    available: bool = True,
    unavailable_reason: str | None = None,
    runtime: str = "python",
) -> Callable[[H], H]:
    """Register a handler class as a node.

    The class must be callable as ``handler(ctx) -> HandlerResult`` and may define a nested
    Pydantic ``Config``. Exactly one of ``code`` (an export template) or ``export_note`` (why the
    node can't be exported) must be given, so export coverage is always an explicit decision.
    """
    if (code is None) == (export_note is None):
        raise ValueError(f"node {type!r}: give exactly one of code= or export_note=")
    if not available and not unavailable_reason:
        raise ValueError(f"node {type!r}: available=False needs unavailable_reason=")

    def deco(cls: H) -> H:
        from athena.core.registry import register_node  # local import: registry imports this module

        meta = NodeMeta(
            type=type, label=label, category=category, description=description,
            inputs=tuple(inputs), outputs=tuple(outputs),
            config=getattr(cls, "Config", None), fields=dict(fields or {}),
            code=code, export_note=export_note,
            available=available, unavailable_reason=unavailable_reason, runtime=runtime,
        )
        cls.meta = meta  # type: ignore[attr-defined]
        register_node(meta, cls())
        return cls

    return deco


# ---- spec building ---------------------------------------------------------------------------

def _literal_options(annotation: Any) -> tuple[str, ...] | None:
    if typing.get_origin(annotation) is Literal:
        return tuple(str(a) for a in typing.get_args(annotation))
    return None


def _strip_optional(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _infer_widget(annotation: Any) -> Widget:
    ann = _strip_optional(annotation)
    if ann is SecretStr:
        return "password"
    if _literal_options(ann):
        return "select"
    if ann is bool:
        return "toggle"
    if ann in (int, float):
        return "number"
    return "text"


def _default_label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def form_fields(config: type[BaseModel] | None, hints: dict[str, FieldUI]) -> list[dict[str, Any]]:
    """An inspector form, in the shape frontend `ConfigField` expects (used for nodes and connectors).

    Field order follows ``hints`` (the declared UI order) and then any remaining ``Config`` fields.
    Secret fields (``SecretStr``) never expose their default value.
    """
    cfg = config or _EmptyConfig
    model_fields = cfg.model_fields
    order = [k for k in hints if k in model_fields] + [k for k in model_fields if k not in hints]
    out: list[dict[str, Any]] = []
    for name in order:
        f = model_fields[name]
        hint = hints.get(name, FieldUI())
        widget = hint.widget or _infer_widget(f.annotation)
        default = f.get_default(call_default_factory=True)
        if isinstance(default, SecretStr):
            default = ""
        entry: dict[str, Any] = {
            "id": name,
            "label": hint.label or f.title or _default_label(name),
            "type": widget,
            "default": default,
        }
        options = hint.options or _literal_options(_strip_optional(f.annotation))
        if widget == "select":
            entry["options"] = list(options or ())
        if hint.accept:
            entry["accept"] = hint.accept
        if hint.mono:
            entry["mono"] = True
        if hint.connector:
            entry["connector"] = hint.connector
        if hint.empty_label:
            entry["empty_label"] = hint.empty_label
        if hint.help or f.description:
            entry["help"] = hint.help or f.description
        for k in ("min", "max", "step"):
            v = getattr(hint, k)
            if v is not None:
                entry[k] = v
        out.append(entry)
    return out


def config_fields(meta: NodeMeta) -> list[dict[str, Any]]:
    return form_fields(meta.config, meta.fields)


def node_spec(meta: NodeMeta) -> dict[str, Any]:
    """The JSON spec served by ``GET /api/nodes`` (mirrored by frontend `NodeSpec`)."""
    return {
        "type": meta.type,
        "label": meta.label,
        "category": meta.category,
        "description": meta.description,
        "inputs": [{"name": p.name, "type": p.type} for p in meta.inputs],
        "outputs": [{"name": p.name, "type": p.type} for p in meta.outputs],
        "config": config_fields(meta),
        "exportable": meta.code is not None,
        "export_note": meta.export_note,
        "available": meta.available,
        "unavailable_reason": meta.unavailable_reason,
        "runtime": meta.runtime,
    }


def render_code(meta: NodeMeta, values: dict[str, Any]) -> str:
    """Fill a node's export template (raises KeyError/IndexError if a value is missing)."""
    if meta.code is None:
        raise ValueError(f"{meta.type} has no export template: {meta.export_note}")
    return meta.code(values) if callable(meta.code) else meta.code.format(**values)


def config_defaults(meta: NodeMeta) -> dict[str, Any]:
    cfg = meta.config or _EmptyConfig
    return {k: f.get_default(call_default_factory=True) for k, f in cfg.model_fields.items()}
