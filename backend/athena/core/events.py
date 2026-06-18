import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EventBroker:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[Any]]] = {}
        self._buffers: dict[str, deque[Any]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue[Any]:
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(q)
        # replay buffered events
        for event in self._buffers.get(run_id, []):
            q.put_nowait(event)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[Any]) -> None:
        if run_id in self._queues:
            try:
                self._queues[run_id].remove(q)
            except ValueError:
                pass

    async def publish(self, run_id: str, event: Any) -> None:
        buf = self._buffers.setdefault(run_id, deque(maxlen=200))
        buf.append(event)
        for q in self._queues.get(run_id, []):
            await q.put(event)

    def is_finished(self, run_id: str) -> bool:
        for event in self._buffers.get(run_id, []):
            if hasattr(event, "type") and event.type == "run_finish":
                return True
        return False

    def cleanup(self, run_id: str) -> None:
        self._queues.pop(run_id, None)
        self._buffers.pop(run_id, None)


broker = EventBroker()
