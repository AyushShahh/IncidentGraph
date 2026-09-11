"""WebSocket manager and endpoint for real-time incident intelligence streaming."""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages active client WebSocket connections and event broadcasting."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self._history: List[Dict[str, Any]] = []
        self._max_history = 200

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("Client connected to WebSocket (total clients: %d)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info("Client disconnected from WebSocket (total clients: %d)", len(self.active_connections))

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast an event payload to all active WebSocket clients."""
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        # Record in in-memory event stream history
        self._history.append(payload)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        dead = set()
        for conn in list(self.active_connections):
            try:
                await conn.send_text(json.dumps(payload, default=str))
            except Exception:
                dead.add(conn)

        for conn in dead:
            self.active_connections.discard(conn)

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._history)


ws_manager = ConnectionManager()


def broadcast_event_sync(event_type: str, data: Dict[str, Any]) -> None:
    """Safe sync helper to schedule broadcast from sync code or background loops."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast(event_type, data))
    except RuntimeError:
        pass


@router.websocket("")
@router.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time bi-directional streaming endpoint for frontend telemetry."""
    await ws_manager.connect(websocket)
    try:
        # Send initial connection greeting and event history snapshot
        await websocket.send_text(json.dumps({
            "type": "init",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "message": "Connected to AI Incident Intelligence Real-time Stream",
                "history": ws_manager.get_history()[-40:],
            }
        }, default=str))

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }))
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket connection terminated: %s", exc)
        ws_manager.disconnect(websocket)
