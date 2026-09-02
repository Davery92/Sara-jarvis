"""
chat_stream's early intercept chain (B3, HYGIENE_AND_STALE_CONTEXT_FIX_PLAN
2026-08-12).

Five commands/situations that skip the normal LLM turn entirely and produce
a direct SSE response instead: chess, code mode, host inspection, UI commands,
and interest-model chat verbs. All five sit
contiguously at the very top of chat_stream's generator, before any of the
setup (event queue, streaming client, intent classification) the rest of
the turn depends on — extracted as a unit for exactly that reason.

Multi-step conversational work is intentionally not intercepted. It stays in
the normal chat tool loop so the active model can use intermediate results,
stream activity, and answer in the same conversation. Durable background work
remains available through explicit research and dispatch tools.

dispatch_intercepts() walks INTERCEPT_HANDLERS in order; the first handler
that returns a non-None stream wins — chat_stream drains it and returns
without reaching the LLM. Each handler's own exceptions are caught and
logged by the dispatcher, same "log and fall through" behavior as the
original inline try/except chain: one broken intercept can't block the
next, or the normal chat flow, from running.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional

from sqlalchemy.orm import Session

from app.core.text_utils import extract_text_content
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)


@dataclass
class ChatTurnContext:
    request: ChatRequest
    current_user: Any
    db: Session
    last_user_message: Optional[str]


def build_context(request: ChatRequest, current_user: Any, db: Session) -> ChatTurnContext:
    """Extract the last user message once, shared by every intercept below
    — the original inline chain re-extracted this identically 6 separate
    times, once per intercept."""
    raw = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
    last_user_message = extract_text_content(raw) if raw else None
    return ChatTurnContext(request=request, current_user=current_user, db=db, last_user_message=last_user_message)


def _ack_stream(content: str, conversation_id: Optional[str], include_full_content: bool = True) -> AsyncIterator[str]:
    """The text_chunk + final_response + done shape shared by every
    intercept that answers with one fixed acknowledgement. Chess omits
    `full_content` in its text_chunk (matches its original, slightly
    inconsistent shape) — every other caller here wants it."""
    async def _gen():
        chunk_data = {"content": content}
        if include_full_content:
            chunk_data["full_content"] = content
        yield f"data: {json.dumps({'type': 'text_chunk', 'data': chunk_data})}\n\n"
        yield f"data: {json.dumps({'type': 'final_response', 'data': {'content': content, 'citations': [], 'timestamp': datetime.now(timezone.utc).isoformat(), 'conversation_id': conversation_id}})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    return _gen()


async def _try_chess(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """CHESS COMMAND INTERCEPTION — /chess commands or an active chess mode."""
    if not (ctx.request.messages and ctx.last_user_message):
        return None
    from app.services.chess_command_handler import handle_chess_command
    chess_result = await handle_chess_command(ctx.current_user.id, ctx.last_user_message, ctx.db)
    if chess_result is None:
        return None
    response_content, _is_streaming = chess_result
    logger.info(f"♟️ Chess command handled: {ctx.last_user_message[:50]}...")
    return _ack_stream(response_content, ctx.request.conversation_id, include_full_content=False)


async def _try_code_mode(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """CODE MODE INTERCEPTION — an active code session bound to this
    conversation, or an explicit /code command. Routes the whole turn to
    the coding harness on the VM."""
    from app.services import code_mode
    if not ctx.last_user_message:
        return None
    is_code_cmd = ctx.last_user_message.strip().lower().startswith("/code")
    # Plain (non-/code) messages only route to code mode when an active
    # session is bound to THIS conversation. Without a conversation_id we
    # must NOT fall back to the user's most recent session — a session
    # created with a NULL/absent conversation_id would otherwise become a
    # global catch-all that hijacks every normal chat turn. Explicit
    # /code commands still follow the user across conversations (their
    # fallback lives in code_mode.run_code_message).
    code_session = (
        code_mode.get_active_session(ctx.db, ctx.current_user.id, ctx.request.conversation_id)
        if ctx.request.conversation_id else None
    )
    if not (code_session or is_code_cmd):
        return None

    logger.info(f"💻 Code mode handling: {ctx.last_user_message[:60]}...")

    async def _gen():
        import asyncio
        queue = asyncio.Queue()
        task = asyncio.create_task(
            code_mode.run_code_message(
                ctx.db, ctx.current_user.id, ctx.request.conversation_id, ctx.last_user_message, queue
            )
        )
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"
        await task  # surface any late exception / ensure cleanup

    return _gen()


async def _try_host_inspection(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """HOST INSPECTION INTERCEPTION — "/host ..." commands, or natural
    "check out <server>" when the named target resolves to a registered
    machine."""
    from app.services import host_command_handler
    if not ctx.last_user_message:
        return None
    host_cmd = host_command_handler.parse_host_command(ctx.last_user_message, ctx.db, ctx.current_user.id)
    if not host_cmd:
        return None
    logger.info(f"🖥️ Host command handling: {host_cmd.get('action')} {host_cmd.get('name', '')}")

    async def _gen():
        async for ev in host_command_handler.run_host_command(ctx.db, ctx.current_user.id, host_cmd):
            yield f"data: {json.dumps(ev)}\n\n"

    return _gen()


async def _try_web_investigation(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """WEB INVESTIGATION INTERCEPTION — "go check out getcara.ai and tell
    me about it" drops into the autonomous background agent (real browser,
    Playwright) rather than an inline web_search answer."""
    from app.services import web_investigation
    if not ctx.last_user_message:
        return None
    urls = web_investigation.detect(ctx.last_user_message, ctx.db, ctx.current_user.id)
    if not urls:
        return None
    logger.info(f"🌐 Web investigation dispatch: {urls}")
    result = await web_investigation.dispatch_investigation(ctx.db, ctx.current_user.id, urls)
    if result.get("status") == "error":
        ack = f"I couldn't start that investigation: {result.get('error')}"
    elif len(urls) == 1:
        ack = (
            f"🔍 On it — I'll open **{urls[0]}** in a real browser, dig through "
            f"the site, and send you a detailed report (with screenshots where "
            f"useful) when I'm done. You can keep chatting meanwhile; watch the "
            f"tasks panel for live progress."
        )
    else:
        url_list = "\n".join(f"- **{u}**" for u in urls)
        ack = (
            f"🔍 On it — I'm opening each of these in a real browser and will "
            f"send you a single combined report comparing them all (with "
            f"screenshots where useful):\n"
            f"{url_list}\n\n"
            f"You can keep chatting meanwhile; watch the tasks panel for live progress."
        )
    return _ack_stream(ack, ctx.request.conversation_id)


async def _try_ui_command(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """UI COMMAND INTERCEPTION — Jarvis-style: "bring up my morning brief" /
    "show me my nutrition" -> a ui_command SSE event the webapp renders as
    an overlay, plus a one-line ack. No LLM call."""
    from app.services import ui_intent
    if not ctx.last_user_message:
        return None
    # iOS clients can navigate to any app screen; the webapp only handles
    # overlay surfaces, so screen intents fall through to the LLM there
    # instead of acking with no visible effect.
    is_ios = str(ctx.request.source or "").startswith("ios")
    ui = ui_intent.parse_ui_intent(ctx.last_user_message, allow_screens=is_ios)
    if not ui:
        return None
    ui_res = ui_intent.resolve_ui_intent(ctx.db, ctx.current_user.id, ui)
    logger.info(f"🪟 UI command: {ui.get('overlay') or ui.get('screen')} (query={ui.get('query')})")

    async def _gen():
        if ui_res.get("command"):
            yield f"data: {json.dumps({'type': 'ui_command', 'data': ui_res['command']})}\n\n"
        async for chunk in _ack_stream(ui_res["ack"], ctx.request.conversation_id):
            yield chunk

    return _gen()


async def _try_interest_model_verb(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """INTEREST MODEL CHAT VERBS (SARA_MIND_V2 §3.2) — "stop pinging me
    about X" / "I care about Y now" -> immediate edit + confirmation, no
    LLM round trip."""
    from app.core.feature_flags import Flag, is_enabled
    if not is_enabled(Flag.MINDV2_BRIEF):
        return None
    if not ctx.last_user_message:
        return None
    from app.services import interest_model
    from app.db.session import get_async_session_factory
    session_factory = get_async_session_factory()
    async with session_factory() as im_db:
        ack = await interest_model.apply_chat_verb(im_db, str(ctx.current_user.id), ctx.last_user_message)
    if not ack:
        return None
    logger.info(f"🎯 Interest model chat verb applied: {ctx.last_user_message[:60]}")
    return _ack_stream(ack, ctx.request.conversation_id)


# "We had the meeting." "I already handled it." "Enough about Laura."
#
# Ground-truth invariant 3. This is deliberately an intercept rather than a
# prompt instruction: on 2026-09-02 David wrote "ENOUGH WITH THE LAURA WEIPPERT
# OVERDUE NONSENSE WE HAD OUR MEETING" and the model, having no closer, cancelled
# two unrelated reminders and edited two notes while the three real threads stayed
# open. When David says a thing is done, closing it must not depend on a model
# choosing to call a tool.
_RESOLUTION_PATTERNS = re.compile(
    r"""
    \b(?:
        we\s+(?:had|already\s+had|did|already\s+did)\s+(?:the|our|that)\s+\w+
      | (?:i|we)\s+(?:already\s+)?(?:handled|answered|replied\s+to|took\s+care\s+of|dealt\s+with|finished|did)\s+(?:it|that|this|them)
      | (?:already|it['\s]?s)\s+(?:handled|done|taken\s+care\s+of|resolved|sorted)
      | (?:stop|quit|enough)\s+(?:with\s+|talking\s+|bugging\s+me\s+|nagging\s+me\s+)?(?:about|on)\b
      | done\s+with\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


async def _try_thread_resolution(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    message = (ctx.last_user_message or "").strip()
    if not message or len(message) > 400:
        return None
    if not _RESOLUTION_PATTERNS.search(message):
        return None

    from app.services.thread_resolution import resolve_entity

    result = await resolve_entity(
        str(ctx.current_user.id), query=message, source="david_chat", reason=message[:200],
    )
    if not result.get("closed"):
        # Nothing matched — say nothing and let the normal turn answer him. An
        # intercept that fires on a phrase but closes nothing would swallow a real
        # conversation.
        return None

    titles = "; ".join(result["threads"][:3])
    extra = ""
    if result["candidates"] or result["notifications"]:
        extra = (
            f" I also dropped {result['candidates']} queued message(s) and cleared "
            f"{result['notifications']} notification(s) about it."
        )
    logger.info(f"🧵 Thread resolution intercept closed {result['closed']}: {titles}")
    return _ack_stream(
        f"Closed — I won't bring it up again: {titles}.{extra}",
        ctx.request.conversation_id,
    )


INTERCEPT_HANDLERS: List[Callable[[ChatTurnContext], Awaitable[Optional[AsyncIterator[str]]]]] = [
    _try_chess,
    _try_code_mode,
    _try_host_inspection,
    _try_ui_command,
    _try_interest_model_verb,
    _try_thread_resolution,
]


async def dispatch_intercepts(ctx: ChatTurnContext) -> Optional[AsyncIterator[str]]:
    """Walk the intercept chain; first match wins. Returns None if nothing
    intercepted the turn — chat_stream proceeds to the normal LLM flow."""
    for handler in INTERCEPT_HANDLERS:
        try:
            stream = await handler(ctx)
            if stream is not None:
                return stream
        except Exception as e:
            logger.error(f"{handler.__name__} interception error: {e}", exc_info=True)
    return None
