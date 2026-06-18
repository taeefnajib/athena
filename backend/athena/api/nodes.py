from fastapi import APIRouter
from athena.core.registry import NODE_REGISTRY

router = APIRouter(prefix="/api/nodes")


@router.get("")
async def list_nodes():
    return {"nodes": list(NODE_REGISTRY.keys())}
