"""
Smart delivery of background task results.

Decision tree:
  1. Web SSE connected + user in chat → persist episode, publish inject_chat_message
  2. Web SSE connected + user NOT in chat → publish show_notification
  3. iOS foregrounded + Sara tab → push with type=task_chat_inject
  4. iOS foregrounded + other tab → push with type=background_task
  5. Nothing active → standard push notification
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def deliver_task_result(
    user_id: str,
    task_id: str,
    task_query: str,
    result_note_id: Optional[str],
    result_note_title: Optional[str],
    result_summary: str,
    db: Session,
):
    """
    Route a completed task result to the best channel for the user.
    """
    from app.routes.task_events import is_sse_connected, publish_task_event
    from app.routes.presence import is_user_in_chat, get_active_clients

    chat_message = _compose_chat_message(task_query, result_summary, result_note_title)

    # --- Path 1 & 2: Web SSE connected ---
    if is_sse_connected(user_id):
        in_chat, _ = is_user_in_chat(user_id)

        if in_chat:
            # Persist as an episode so it shows up on reload too
            conversation_id = _get_active_conversation_id(user_id, db)
            if conversation_id:
                _persist_task_result_episode(
                    user_id, conversation_id, chat_message, result_note_id, db
                )
            publish_task_event(user_id, {
                "type": "inject_chat_message",
                "content": chat_message,
                "task_id": task_id,
                "note_id": result_note_id,
            })
            logger.info(f"Delivered task {task_id} via SSE inject_chat_message")
        else:
            publish_task_event(user_id, {
                "type": "show_notification",
                "title": "Background task complete",
                "message": _short_summary(task_query),
                "task_id": task_id,
                "note_id": result_note_id,
            })
            logger.info(f"Delivered task {task_id} via SSE show_notification")
        return

    # --- Path 3, 4, 5: Check iOS / push ---
    active_clients = get_active_clients(user_id)
    ios_clients = [c for c in active_clients if c.get("platform") == "ios" and c.get("visible")]

    if ios_clients:
        ios_client = ios_clients[0]
        ios_view = ios_client.get("current_view", "")
        in_sara_tab = ios_view in ("chat", "sara", "Sara")

        if in_sara_tab:
            # Persist episode first so iOS can reload it
            conversation_id = _get_active_conversation_id(user_id, db)
            if conversation_id:
                _persist_task_result_episode(
                    user_id, conversation_id, chat_message, result_note_id, db
                )
            await _send_push(user_id, {
                "type": "task_chat_inject",
                "task_id": task_id,
                "note_id": result_note_id,
                "conversation_id": conversation_id,
            }, "Background task complete", _short_summary(task_query), db)
            logger.info(f"Delivered task {task_id} via iOS push task_chat_inject")
        else:
            await _send_push(user_id, {
                "type": "background_task",
                "task_id": task_id,
                "status": "completed",
                "note_id": result_note_id,
            }, "Background task complete", _short_summary(task_query), db)
            logger.info(f"Delivered task {task_id} via iOS push background_task")
        return

    # --- Path 5: Nobody's home — standard push ---
    await _send_push(user_id, {
        "type": "background_task",
        "task_id": task_id,
        "status": "completed",
        "note_id": result_note_id,
    }, "Background task complete", _short_summary(task_query), db)
    logger.info(f"Delivered task {task_id} via fallback push notification")


# --- Helpers ---


def _compose_chat_message(query: str, summary: str, note_title: Optional[str]) -> str:
    """Build a Sara-voice message for the completed task result."""
    parts = [f"Your background research is ready! Here's what I found:\n\n{summary}"]
    if note_title:
        parts.append(f"\nFull report saved to your workspace: **{note_title}**")
    return "\n".join(parts)


def _short_summary(query: str) -> str:
    """Truncate query for notification body."""
    preview = query[:80]
    if len(query) > 80:
        preview += "..."
    return f"Your agents finished: {preview}"


def _get_active_conversation_id(user_id: str, db: Session) -> Optional[str]:
    """Look up the user's active conversation from profile_data."""
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT profile_data FROM user_profile WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        if row and row[0]:
            return row[0].get("active_conversation_id")
    except Exception as e:
        logger.warning(f"Failed to get active conversation: {e}")
    return None


def _persist_task_result_episode(
    user_id: str,
    conversation_id: str,
    message: str,
    note_id: Optional[str],
    db: Session,
):
    """Insert an assistant episode into the active conversation so it survives reload."""
    try:
        from app.models.episode import Episode

        episode = Episode(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=message,
            importance=0.4,
            base_importance=0.4,
            source="background_task",
            memory_type="conversation",
            meta={"note_id": note_id, "injected": True},
        )
        db.add(episode)
        db.commit()
        logger.info(f"Persisted task result episode to conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Failed to persist task result episode: {e}")
        try:
            db.rollback()
        except Exception:
            pass


async def _send_push(
    user_id: str,
    data: dict,
    title: str,
    body: str,
    db: Session,
):
    """Send push notification to all of the user's devices."""
    try:
        from app.main_simple import PushToken, SessionLocal

        push_db = SessionLocal()
        try:
            push_tokens = push_db.query(PushToken).filter(
                PushToken.user_id == user_id,
                PushToken.is_active == True,
            ).all()

            if not push_tokens:
                return

            messages = [
                {
                    "to": token.token,
                    "sound": "default",
                    "title": title,
                    "body": body,
                    "data": data,
                }
                for token in push_tokens
            ]

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=messages,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code == 200:
                    logger.info(f"Sent push to {len(push_tokens)} devices")
                else:
                    logger.warning(f"Push returned {response.status_code}: {response.text}")
        finally:
            push_db.close()
    except Exception as e:
        logger.warning(f"Failed to send push: {e}")
