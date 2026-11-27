"""Registered connectors. Populated by ``@connector`` (athena.sdk) when connector modules and plugins import."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from athena.sdk.connector import ConnectorMeta

CONNECTOR_REGISTRY: dict[str, Any] = {}
CONNECTOR_META: dict[str, ConnectorMeta] = {}


def register_connector(meta: ConnectorMeta, impl: Any) -> None:
    if meta.type in CONNECTOR_REGISTRY:
        raise ValueError(f"Duplicate connector type: {meta.type}")
    CONNECTOR_REGISTRY[meta.type] = impl
    CONNECTOR_META[meta.type] = meta


def get_connector(conn_type: str) -> tuple[ConnectorMeta, Any]:
    if conn_type not in CONNECTOR_META:
        raise KeyError(f"Unknown connector type: {conn_type!r}")
    return CONNECTOR_META[conn_type], CONNECTOR_REGISTRY[conn_type]
