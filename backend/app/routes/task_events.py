"""
Task Events SSE — streams background task results to connected web clients.

Two event types:
  - inject_chat_message: result should appear as a Sara message in chat
  - show_notification: result should appear as an in-app toast/banner
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Set

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_user
from app.db.session import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/task-events", tags=["Task Events"])

# Track which users have active SSE connections
# Maps user_id -> set of client connection IDs
_sse_connections: Dict[str, Set[str]] = {}


def _channel_for(user_id: str) -> str:
    return f"sara:task_events:{user_id}"


def is_sse_connected(user_id: str) -> bool:
    """Check if any webapp SSE client is connected for this user."""
    return bool(_sse_connections.get(user_id))


def publish_task_event(user_id: str, event_dict: dict) -> bool:
    """
    Publish a task event to the user's SSE channel via Redis.
    Returns True if published successfully.
    """
    try:
        from app.core.redis import get_redis_sync
        r = get_redis_sync()
        channel = _channel_for(user_id)
        r.publish(channel, json.dumps(event_dict))
        logger.info(f"Published task event to {channel}: type={event_dict.get('type')}")
        return True
    except Exception as e:
        logger.error(f"Failed to publish task event: {e}")
        return False


@router.get("/stream")
async def stream_task_events(
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream background task result events via SSE for the authenticated user."""
    user_id = current_user.id
    # Release the auth DB session's connection immediately. FastAPI keeps `yield`
    # dependencies (get_db) alive until the response finishes, so on a long-lived
    # SSE stream the auth SELECT's transaction would sit idle and Postgres kills it
    # ("idle-in-transaction timeout") after 5 min. The stream itself uses Redis, not
    # the DB, so we don't need this session.
    try:
        db.close()
    except Exception:
        pass

    async def event_generator() -> AsyncGenerator[str, None]:
        # Register this connection
        conn_id = f"{id(request)}"
        if user_id not in _sse_connections:
            _sse_connections[user_id] = set()
        _sse_connections[user_id].add(conn_id)
        logger.info(f"SSE task-events client connected: user={user_id} conn={conn_id}")

        # Connect to Redis pub/sub
        r = None
        pubsub = None
        try:
            from app.core.redis import get_redis_sync
            r = get_redis_sync()
            pubsub = r.pubsub()
            pubsub.subscribe(_channel_for(user_id))
        except Exception as e:
            logger.error(f"Redis connection failed for task-events SSE: {e}")

        try:
            # Send initial keepalive
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                # Poll Redis for messages
                if pubsub:
                    message = pubsub.get_message(timeout=0.1)
                    if message and message["type"] == "message":
                        try:
                            yield f"data: {message['data']}\n\n"
                        except Exception:
                            pass

                # Keepalive every 15s (prevents proxy timeouts)
                await asyncio.sleep(0.5)

        finally:
            # Unregister connection
            if user_id in _sse_connections:
                _sse_connections[user_id].discard(conn_id)
                if not _sse_connections[user_id]:
                    del _sse_connections[user_id]
            if pubsub:
                pubsub.close()
            logger.info(f"SSE task-events client disconnected: user={user_id} conn={conn_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
