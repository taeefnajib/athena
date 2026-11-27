from typing import Any

from fastapi import APIRouter

from athena.plugins import load_plugins
from athena.core.registry import CATEGORIES, NODE_META
from athena.sdk import node_spec

load_plugins()
router = APIRouter(prefix="/api/nodes")


@router.get("")
async def list_nodes() -> dict[str, Any]:
    """Every registered node's full spec. The frontend builds its library and forms from this."""
    return {
        "categories": [{"id": k, **v} for k, v in CATEGORIES.items()],
        "nodes": [node_spec(m) for m in NODE_META.values()],
    }
