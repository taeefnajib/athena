"""Where nodes can run: the local worker, a local Ray cluster, and saved Ray cluster connections."""
from typing import Any

import anyio
from fastapi import APIRouter

from athena.runtime import adapters

router = APIRouter(prefix="/api/runtimes")


@router.get("")
async def runtimes() -> dict[str, Any]:
    return {"runtimes": await anyio.to_thread.run_sync(adapters.available)}
