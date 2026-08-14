"""
chat_stream's "a turn started" preamble (B3, HYGIENE_AND_STALE_CONTEXT_FIX_PLAN
2026-08-12).

Five best-effort, fire-and-forget side effects that used to sit inline at
the top of chat_stream, ~140 lines drowning the endpoint before it does
anything a user actually sees: signal the activity state machine, tell the
ACS daemon a conversation is happening, run the shadow kernel engaged_turn
proof call, update the unified context snapshot + cross-device session,
and emit CHAT_MESSAGE_RECEIVED for working-memory/salience subscribers.

None of these may add latency to or block the real chat response — that
was true in the original inline code and stays true here. The one
exception is the activity-state signal, which the original ran
synchronously inline (not via `ensure_future`); `notify_turn_started`
preserves that ordering by awaiting it directly while firing the other
four as background tasks, matching original behavior exactly rather than
"cleaning it up" into uniform fire-and-forget.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.text_utils import extract_text_content

logger = logging.getLogger(__name__)


def _last_user_text(request) -> str:
    for m in reversed(request.messages):
        role = m.role if hasattr(m, "role") else m.get("role")
        if role == "user":
            content = m.content if hasattr(m, "content") else m.get("content")
            return extract_text_content(content) if content else ""
    return ""


async def _signal_activity_state() -> None:
    try:
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal
        activity_state_machine.process_signal(ActivitySignal(
            signal_type="interaction",
            source="chat_stream",
            value="message",
        ))
    except Exception as exc:
        from app.core.swallow import swallow
        await swallow(logger, "chat_stream.activity_signal", exc)


async def _post_acs_activity_event(last_user_text: str) -> None:
    """Post an external_event to the ACS daemon's activity log so her next
    think turn sees that David is talking to chat-Sara right now."""
    try:
        from app.core.config import settings
        if not (last_user_text and getattr(settings, "acs_daemon_token", "")):
            return
        import httpx
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                await client.post(
                    "http://127.0.0.1:8000/api/acs/v2/activity",
                    json={
                        "kind": "external_event",
                        "summary": f"David in chat: {last_user_text[:160]}",
                        "body": last_user_text[:2000],
                        "tags": ["chat", "david"],
                        "metadata": {"source": "chat_stream"},
                    },
                    headers={"X-Daemon-Token": settings.acs_daemon_token},
                )
        except Exception as exc:
            from app.core.swallow import swallow
            await swallow(logger, "chat_stream.acs_event_post", exc)
    except Exception as exc:
        from app.core.swallow import swallow
        await swallow(logger, "chat_stream.acs_event_post_setup", exc)


async def _shadow_kernel_engaged_turn(user_id: str, last_user_text: str, conversation_id) -> None:
    """SINGULAR_SARA_MASTER_PLAN §C4 shadow-only proof call. Fire-and-forget:
    never awaited inline, never touches the response David gets. The proof
    this existed for (engaged-state context assembly correctness) is done —
    SINGULAR_CONTEXT is the real live path now — so this only still runs
    pre-cutover, when SINGULAR_KERNEL is on but SINGULAR_CONTEXT isn't."""
    try:
        from app.core.feature_flags import Flag, is_enabled
        if not (is_enabled(Flag.SINGULAR_KERNEL) and not is_enabled(Flag.SINGULAR_CONTEXT)):
            return
        from app.services.kernel import engaged_turn
        try:
            await engaged_turn(user_id, conversation_id=conversation_id, message_preview=last_user_text)
        except Exception as exc:
            logger.debug(f"[kernel] shadow engaged_turn failed: {exc}")
    except Exception:
        pass  # Non-critical — the shadow path must never affect real chat


async def _update_context_snapshot(user_id: str, request) -> None:
    """Update the unified context snapshot + cross-device active session:
    David is chatting now."""
    try:
        from app.services.context_writer import update_fields as ctx_update
        device = getattr(request, "source", None) or "unknown"
        await ctx_update(
            user_id, source="chat_stream",
            last_chat_at=datetime.now(timezone.utc).isoformat(),
            hours_since_last_chat=0.0,
            has_chatted_today=True,
            turn_count=len(request.messages),
            active_conversation_id=request.conversation_id,
            active_conversation_device=device,
        )
        # A brand-new conversation has no id yet — skip it here; the
        # post-stream update (elsewhere in chat_stream) stamps the real id.
        if request.conversation_id:
            from app.routes.session import update_active_session
            await update_active_session(
                user_id=user_id,
                conversation_id=request.conversation_id,
                device=device,
                turn_count=len(request.messages),
            )
    except Exception as exc:
        from app.core.swallow import swallow
        await swallow(logger, "chat_stream.context_writer_update", exc)


async def _emit_chat_message_received(user_id: str, request) -> None:
    """Emit CHAT_MESSAGE_RECEIVED for working memory + salience subscribers."""
    try:
        from app.services.event_bus import emit_event, EventType
        last_msg = _last_user_text(request)
        await emit_event(
            event_type=EventType.CHAT_MESSAGE_RECEIVED,
            user_id=user_id,
            payload={"topic": last_msg[:100] if last_msg else "", "turn_count": len(request.messages)},
            source="chat_stream",
        )
    except Exception as exc:
        from app.core.swallow import swallow
        await swallow(logger, "chat_stream.event_bus_emit", exc)


async def notify_turn_started(current_user: Any, request) -> None:
    """Fire every "a chat turn started" side effect. Call once, near the
    top of chat_stream, before any real work begins. Never raises."""
    user_id = str(current_user.id)
    last_user_text = _last_user_text(request)

    await _signal_activity_state()  # synchronous in the original — awaited inline, not backgrounded
    asyncio.ensure_future(_post_acs_activity_event(last_user_text))
    asyncio.ensure_future(_shadow_kernel_engaged_turn(user_id, last_user_text, request.conversation_id))
    asyncio.ensure_future(_update_context_snapshot(user_id, request))
    asyncio.ensure_future(_emit_chat_message_received(user_id, request))
