"""The connector SDK: how Athena talks to external systems (databases, warehouses, storage, APIs).

A connector declares a Pydantic ``Config`` (``SecretStr`` fields are secrets: they are stored in the
OS keychain and never written to .athena files or exports), and implements ``test``, ``list`` and
``read``. Users save configured *connections* by name; nodes refer to a connection by name only.

    from athena.sdk import connector, ConnectorBase, Resource, TestResult

    @connector("my_api", label="My API", category="api", description="...",
               library="requests", license="Apache-2.0")
    class MyApi(ConnectorBase):
        class Config(BaseModel):
            base_url: str = "https://api.example.com"
            token: SecretStr = SecretStr("")
        def test(self, cfg): ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from pydantic import BaseModel, SecretStr

from athena.sdk.node import FieldUI, form_fields

if TYPE_CHECKING:
    import pandas as pd

CONNECTOR_CATEGORIES = {
    "database": "Databases",
    "warehouse": "Warehouses",
    "storage": "Object storage & files",
    "api": "APIs & SaaS",
    "tracking": "Experiment tracking",
    "model_provider": "Model providers",
    "vector_store": "Vector stores",
}


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resource:
    """Something a connection can read: a schema, a table, a bucket, a file, an endpoint."""

    path: str            # full path to pass back to list()/read(), e.g. "public.customers"
    name: str            # display name, e.g. "customers"
    kind: str            # "schema" | "table" | "view" | "file" | ...
    has_children: bool = False


class ConnectorBase:
    """Override the methods your connector supports. ``cfg`` is the validated Config with secrets resolved."""

    Config: type[BaseModel]

    def test(self, cfg: Any) -> TestResult:
        raise NotImplementedError

    def list(self, cfg: Any, path: str | None = None) -> list[Resource]:
        return []

    def read(self, cfg: Any, query: str, limit: int | None = None) -> pd.DataFrame:
        raise NotImplementedError(f"{type(self).__name__} can't read data")


@dataclass(frozen=True)
class ConnectorMeta:
    type: str
    label: str
    category: str
    description: str
    config: type[BaseModel]
    fields: dict[str, FieldUI]
    library: str
    """The library this connector wraps, as shown to users (e.g. "SQLAlchemy")."""
    license: str
    """License of the connector *and* the library it relies on, e.g. "MIT (SQLAlchemy)"."""
    extras: dict[str, str] = field(default_factory=dict)
    """Optional installs, e.g. {"PostgreSQL": "pip install 'athena-backend[postgres]'"}."""

    @property
    def secret_fields(self) -> list[str]:
        return [k for k, f in self.config.model_fields.items() if f.annotation is SecretStr]


C = TypeVar("C", bound=type)


def connector(
    type: str,
    *,
    label: str,
    category: str,
    description: str,
    library: str,
    license: str,
    fields: dict[str, FieldUI] | None = None,
    extras: dict[str, str] | None = None,
) -> Callable[[C], C]:
    if category not in CONNECTOR_CATEGORIES:
        raise ValueError(f"connector {type!r}: unknown category {category!r}")

    def deco(cls: C) -> C:
        from athena.connectors.registry import register_connector

        cfg = getattr(cls, "Config", None)
        if cfg is None:
            raise ValueError(f"connector {type!r} needs a nested Config model")
        meta = ConnectorMeta(type, label, category, description, cfg, dict(fields or {}), library, license, dict(extras or {}))
        cls.meta = meta  # type: ignore[attr-defined]
        register_connector(meta, cls())
        return cls

    return deco


def connector_spec(meta: ConnectorMeta) -> dict[str, Any]:
    """Served by GET /api/connectors; the frontend builds the "New connection" form from it."""
    return {
        "type": meta.type,
        "label": meta.label,
        "category": meta.category,
        "category_label": CONNECTOR_CATEGORIES[meta.category],
        "description": meta.description,
        "config": form_fields(meta.config, meta.fields),
        "secret_fields": meta.secret_fields,
        "library": meta.library,
        "license": meta.license,
        "extras": meta.extras,
    }
