"""WebSocket manager and endpoint for real-time incident intelligence streaming."""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Union
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.logging import get_logger
from backend.redis.client import get_redis_client

logger = get_logger(__name__)

router = APIRouter()

REDIS_EVENTS_CHANNEL = "incident_events_stream"
REDIS_EVENTS_HISTORY_KEY = "incident_events_history"
MAX_HISTORY_ENTRIES = 200


class ConnectionManager:
    """Manages active client WebSocket connections, Redis Pub/Sub synchronization, and event broadcasting."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self._history: List[Dict[str, Any]] = []
        self._max_history = MAX_HISTORY_ENTRIES
        self._listener_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("Client connected to WebSocket (active clients: %d)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info("Client disconnected from WebSocket (active clients: %d)", len(self.active_connections))

    async def _send_to_local_clients(self, payload: Dict[str, Any]) -> None:
        """Send a JSON payload to all currently connected local WebSockets."""
        if not self.active_connections:
            return
        dead = set()
        text_data = json.dumps(payload, default=str)
        for conn in list(self.active_connections):
            try:
                await conn.send_text(text_data)
            except Exception:
                dead.add(conn)
        for conn in dead:
            self.active_connections.discard(conn)

    def _format_event(
        self,
        event_or_type: Union[str, Dict[str, Any]],
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Normalize event payloads to a consistent schema."""
        now_iso = datetime.now(timezone.utc).isoformat()
        if isinstance(event_or_type, dict):
            payload = dict(event_or_type)
            if "id" not in payload:
                payload["id"] = f"ev-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{uuid.uuid4().hex[:4]}"
            if "timestamp" not in payload:
                payload["timestamp"] = now_iso
            if "data" not in payload:
                payload["data"] = {}
            if "type" not in payload:
                payload["type"] = "event:general"
            # Ensure top-level convenience fields if present in data
            if "service" not in payload and "primary_service" in payload.get("data", {}):
                payload["service"] = payload["data"]["primary_service"]
            if "message" not in payload and "message" in payload.get("data", {}):
                payload["message"] = payload["data"]["message"]
            return payload

        event_type = str(event_or_type)
        data_dict = data or {}
        payload = {
            "id": f"ev-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{uuid.uuid4().hex[:4]}",
            "type": event_type,
            "timestamp": now_iso,
            "incident_id": kwargs.get("incident_id") or data_dict.get("incident_id"),
            "service": kwargs.get("service") or data_dict.get("primary_service") or data_dict.get("service"),
            "severity": kwargs.get("severity") or data_dict.get("severity"),
            "message": kwargs.get("message") or data_dict.get("message") or f"{event_type} event",
            "data": data_dict,
        }
        return payload

    async def broadcast(
        self,
        event_or_type: Union[str, Dict[str, Any]],
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Broadcast an event across all processes via Redis Pub/Sub, updating history."""
        payload = self._format_event(event_or_type, data, **kwargs)

        # Update in-memory fallback history
        self._history.append(payload)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Publish to Redis channel & store in Redis history list
        published_to_redis = False
        try:
            redis = await get_redis_client()
            serialized = json.dumps(payload, default=str)
            await redis.lpush(REDIS_EVENTS_HISTORY_KEY, serialized)
            await redis.ltrim(REDIS_EVENTS_HISTORY_KEY, 0, self._max_history - 1)
            await redis.publish(REDIS_EVENTS_CHANNEL, serialized)
            published_to_redis = True
        except Exception as exc:
            logger.debug("Redis publish failed, falling back to local dispatch: %s", exc)

        # If Redis wasn't available or listener isn't running, dispatch directly to local WebSockets
        if not published_to_redis or not self._running:
            await self._send_to_local_clients(payload)

    async def get_history_async(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent events from Redis list, falling back to in-memory history."""
        try:
            redis = await get_redis_client()
            raw_items = await redis.lrange(REDIS_EVENTS_HISTORY_KEY, 0, limit - 1)
            if raw_items:
                events = []
                for item in raw_items:
                    try:
                        events.append(json.loads(item))
                    except Exception:
                        pass
                if events:
                    return events
        except Exception as exc:
            logger.debug("Redis history read failed, using in-memory: %s", exc)

        if self._history:
            return list(reversed(self._history[-limit:]))

        # Default system startup placeholder event if empty
        return [
            {
                "id": f"ev-init-{int(datetime.now(timezone.utc).timestamp())}",
                "type": "system:online",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "platform",
                "message": "IncidentGraph real-time event pipeline active and monitoring.",
                "data": {"status": "healthy"},
            }
        ]

    def get_history(self) -> List[Dict[str, Any]]:
        """Sync accessor for history."""
        return list(reversed(self._history[-50:]))

    async def start_redis_listener(self) -> None:
        """Background task running inside backend to forward Redis pub/sub messages to WebSockets."""
        self._running = True
        logger.info("Starting Redis pub/sub subscriber on channel '%s'...", REDIS_EVENTS_CHANNEL)
        while self._running:
            try:
                redis = await get_redis_client()
                pubsub = redis.pubsub()
                await pubsub.subscribe(REDIS_EVENTS_CHANNEL)
                logger.info("Successfully subscribed to Redis channel '%s'", REDIS_EVENTS_CHANNEL)

                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message and message.get("type") == "message":
                        raw_data = message.get("data")
                        if raw_data:
                            try:
                                payload = json.loads(raw_data)
                                await self._send_to_local_clients(payload)
                            except Exception as e:
                                logger.debug("Error parsing pubsub message: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    logger.warning("Redis subscriber error: %s. Reconnecting in 3s...", exc)
                    await asyncio.sleep(3)

    def stop_redis_listener(self) -> None:
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None


ws_manager = ConnectionManager()


async def broadcast_event(
    event_or_type: Union[str, Dict[str, Any]],
    data: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    """Universal async broadcast function callable anywhere across backend services."""
    await ws_manager.broadcast(event_or_type, data, **kwargs)


def broadcast_event_sync(
    event_or_type: Union[str, Dict[str, Any]],
    data: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    """Safe sync helper to schedule broadcast from synchronous code, tasks, or worker processes."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast(event_or_type, data, **kwargs))
    except RuntimeError:
        # If running in a thread/worker without an active loop, spin up an event loop to publish
        try:
            asyncio.run(ws_manager.broadcast(event_or_type, data, **kwargs))
        except Exception as err:
            logger.debug("broadcast_event_sync execution error: %s", err)


@router.websocket("")
@router.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time bi-directional streaming endpoint for frontend telemetry."""
    await ws_manager.connect(websocket)
    try:
        # Retrieve recent history from Redis
        history = await ws_manager.get_history_async(limit=40)
        await websocket.send_text(
            json.dumps({
                "type": "init",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "message": "Connected to IncidentGraph Real-time Stream",
                    "history": history,
                },
            }, default=str)
        )

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(
                        json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    )
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket connection terminated: %s", exc)
        ws_manager.disconnect(websocket)
