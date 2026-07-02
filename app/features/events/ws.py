"""Real-time event attendee-count updates over WebSocket.

Each connected client subscribes (via Redis pub/sub) to its event's channel and
receives the live attendee count. When a ticket purchase is confirmed, the
payments service publishes the new count to that channel, fanning it out to every
connected client. The count is public event information, so the socket is open
(no authentication required).
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.features.attendees import services as attendees_services

router = APIRouter()


def _channel(event_id: uuid.UUID) -> str:
    """Redis pub/sub channel carrying an event's attendee-count updates."""
    return f"event:attendees:{event_id}"


def _payload(total: int, checked_in: int) -> str:
    """Serialize an attendee-count message."""
    return json.dumps({"attendee_count": total, "checked_in": checked_in})


async def broadcast_attendee_count(db, event_id: uuid.UUID) -> None:
    """Publish an event's current attendee count to its channel (best-effort)."""
    total, checked_in = await attendees_services.count_for_event(db, event_id)
    await get_redis().publish(_channel(event_id), _payload(total, checked_in))


@router.websocket("/ws/events/{event_id}")
async def event_attendee_count_ws(websocket: WebSocket, event_id: uuid.UUID) -> None:
    """Stream live attendee-count updates for an event.

    Sends an initial snapshot on connect, then forwards every published update
    until the client disconnects.
    """
    await websocket.accept()

    # Initial snapshot so clients render immediately without waiting for a sale.
    async with async_session_factory() as db:
        total, checked_in = await attendees_services.count_for_event(db, event_id)
    await websocket.send_text(_payload(total, checked_in))

    channel = _channel(event_id)
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel)

    async def _forward() -> None:
        async for message in pubsub.listen():
            if message.get("type") == "message":
                await websocket.send_text(message["data"])

    async def _drain() -> None:
        # Reads (and ignores) client frames so a disconnect ends the connection.
        while True:
            await websocket.receive_text()

    forward = asyncio.create_task(_forward())
    drain = asyncio.create_task(_drain())
    try:
        await asyncio.wait({forward, drain}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        forward.cancel()
        drain.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
