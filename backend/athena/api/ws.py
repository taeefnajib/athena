import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from athena.core.events import broker

router = APIRouter()


@router.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str):
    await websocket.accept()

    # If run already finished, send buffered events and close
    if broker.is_finished(run_id):
        for event in list(broker._buffers.get(run_id, [])):
            try:
                data = event.model_dump() if hasattr(event, "model_dump") else event
                await websocket.send_text(json.dumps(data, default=str))
            except Exception:
                pass
        await websocket.close()
        return

    q = broker.subscribe(run_id)
    try:
        while True:
            event = await q.get()
            try:
                data = event.model_dump() if hasattr(event, "model_dump") else event
                await websocket.send_text(json.dumps(data, default=str))
            except Exception:
                break
            if hasattr(event, "type") and event.type == "run_finish":
                break
    except WebSocketDisconnect:
        pass
    finally:
        broker.unsubscribe(run_id, q)
        try:
            await websocket.close()
        except Exception:
            pass
