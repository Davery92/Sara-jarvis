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

from sqlalchemy.orm import Session

from app.services.unified_notification import send_notification

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

    # Tell-once ledger: a task completion is a one-shot fact. Whatever path
    # re-invokes delivery later (resume, recovery, a second caller), David
    # hears about a given task_id exactly once, ever.
    if _already_delivered(user_id, task_id, db):
        logger.info(f"Task {task_id} completion already delivered once — skipping re-delivery")
        return
    # Record BEFORE sending: if a send half-fails we'd rather miss one ping
    # than ever repeat one — repeats are the failure mode that erodes trust.
    _record_delivered(user_id, task_id, task_query, db)

    # SARA_UNLEASHED Phase T.2: never push raw agent output. Dispatch results
    # sometimes ARE the agent's literal last turn ("Now I have enough
    # research to build the comprehensive document. Let me create it:") —
    # chain-of-thought as a notification body. Every delivery gets a
    # summarize pass first: what was produced, where it lives, the next
    # action. Falls back to a safe generic line (never the raw text) on
    # any failure — a leak is worse than a generic line.
    result_summary = await _summarize_for_delivery(task_query, result_summary, result_note_title)

    # Verification habit (Phase 9.3): before telling David it's done, Sara actually
    # checks the output — did an artifact get produced with real content, and does the
    # summary read like success? Kills the "pushed 'failed' when the output was fine"
    # class (and its inverse). The verdict is advisory: it annotates, never blocks.
    try:
        verdict = await _verify_result(task_query, result_summary, result_note_id, db)
        if verdict and verdict.get("note"):
            result_summary = f"{result_summary}\n\n_(verified: {verdict['note']})_"
    except Exception as _ve:
        logger.debug(f"result verification skipped: {_ve}")

    chat_message = _compose_chat_message(task_query, result_summary, result_note_title)

    await _dual_write_candidate(user_id, task_id, task_query, result_summary)
    await _fulfill_commitment(user_id, task_id, result_summary)

    # --- Path 0: Active desktop (Desktop Jarvis Overhaul D) — HUD toast
    # with an "Open report" overlay action beats everything else; it's the
    # richest surface and doesn't compete with a push buzzing his phone.
    try:
        from app.services.command_router import command_router

        if command_router.get_connected_devices(user_id):
            await send_notification(
                user_id=user_id,
                title=_task_subject(task_query),
                message=_push_body(result_summary),
                category="agent_task",
                topic=f"agent_task:{task_id}",
                source="task_result_delivery",
                priority="normal",
                overlay={"kind": "report", "payload": {"latest": True}},
                db=db,
            )
            # send_notification doesn't commit a caller-supplied session (see
            # mindv2_deliver.py's identical fix, 2026-07-30).
            await db.commit()
            logger.info(f"Delivered task {task_id} via desktop toast + report overlay")
            return
    except Exception as e:
        logger.debug(f"Desktop delivery check failed, falling through to SSE/push: {e}")

    # When the task produced a report note, the completion push should DEEP-LINK
    # straight to that note on tap. The iOS handler opens the note directly for
    # `research_complete` (navigateToNoteEditor(data.note_id)), whereas
    # `background_task` only routes to the inbox — so pick the note-opening type
    # whenever we have a note. (`background_task` stays for note-less tasks.)
    note_push_type = "research_complete" if result_note_id else "background_task"

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
                "title": _task_subject(task_query),
                "message": _push_body(result_summary),
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
            await send_notification(
                user_id=user_id,
                title=_task_subject(task_query),
                message=_push_body(result_summary),
                category="background_task",
                topic=f"agent_task:{task_id}",
                source="task_result_delivery",
                priority="normal",
                extra_push_data={
                    "type": "task_chat_inject",
                    "task_id": task_id,
                    "note_id": result_note_id,
                    "conversation_id": conversation_id,
                },
                db=db,
            )
            await db.commit()
            logger.info(f"Delivered task {task_id} via iOS push task_chat_inject")
        else:
            await send_notification(
                user_id=user_id,
                title=_task_subject(task_query),
                message=_push_body(result_summary),
                category="background_task",
                topic=f"agent_task:{task_id}",
                source="task_result_delivery",
                priority="normal",
                extra_push_data={
                    "type": note_push_type,
                    "task_id": task_id,
                    "status": "completed",
                    "note_id": result_note_id,
                    "result_note_id": result_note_id,
                },
                db=db,
            )
            await db.commit()
            logger.info(f"Delivered task {task_id} via iOS push {note_push_type}")
        return

    # --- Path 5: Nobody's home — standard push ---
    # Item 4 (registers=1 closure, 2026-07-31): legacy fallback push
    # deleted. MOUTH_ONLY_TASK_RESULT_DELIVERY ran flag-safe long enough
    # to confirm the say_candidate dual-write (above, unconditional,
    # called before any path branch) is the only path needed here.
    # Paths 0-4 (active desktop HUD, SSE, iOS push with rich routing)
    # are a genuinely better UX than the mouth pipeline replicates today
    # and stay untouched — this deletion is Path 5 only.
    logger.info(f"[mouth-only] task_result_delivery candidate queued: agent_task:{task_id}")
    # _record_delivered above (tell-once ledger) still needs this commit —
    # it wrote to `db` before any path branch, and nothing else on this
    # path persists it now that Path 5 no longer sends its own push.
    await db.commit()


async def _dual_write_candidate(user_id: str, task_id: str, task_query: str, result_summary: str) -> None:
    """Mind V2 rewire plan Workstream B.5 — feed the say_candidate queue
    with the same real completion content every delivery path below
    already sends, once per task (the tell-once ledger above already
    guarantees this is reached at most once per task_id). Needs its own
    AsyncSession — the `db` passed into deliver_task_result is a sync
    Session used for the ledger/episode writes, not awaitable. Wrapped so
    a candidate-queue failure never breaks delivery, which stays on the
    sync path untouched below."""
    try:
        from datetime import timedelta
        from app.core.timezone import now as local_now
        from app.services.say_candidate import create_candidate
        from app.db.session import get_async_session_factory

        topic = f"agent_task:{task_id}"
        factory = get_async_session_factory()
        async with factory() as adb:
            await create_candidate(
                adb, user_id=user_id, source="task_result_delivery", kind="inform",
                summary=result_summary[:2000],
                evidence=[{"task_id": task_id, "query": (task_query or "")[:200]}],
                topic_entities=[topic],
                valid_until=local_now() + timedelta(hours=12),
                dedupe_key=topic,
            )
    except Exception as e:
        logger.warning(f"[say_candidate] task_result_delivery dual-write failed: {e}")


async def _fulfill_commitment(user_id: str, task_id: str, result_summary: str) -> None:
    """Mind V2 rewire plan Workstream D.3 — close the sara_commitment opened
    at dispatch time (DispatchAndMonitorTool._record_commitment) now that
    the completion notice is actually reaching one of the delivery paths
    below. make_candidate=False: the delivery paths below already tell
    David the result — a second "commitment closed" candidate would just
    repeat it. Best-effort: a ledger miss must never block delivery."""
    try:
        from app.services.commitment_service import list_open_commitments, close_commitment
        from app.db.session import get_async_session_factory

        marker = f"task:{task_id}"
        factory = get_async_session_factory()
        async with factory() as db:
            open_commitments = await list_open_commitments(db, user_id)
            for c in open_commitments:
                if c.get("trigger_description") == marker:
                    await close_commitment(
                        db, user_id, c["id"],
                        closure_note=result_summary[:500],
                        make_candidate=False,
                    )
    except Exception as e:
        logger.warning(f"[commitment] fulfillment check failed for task {task_id}: {e}")


# --- Helpers ---


async def _verify_result(task_query: str, result_summary: str,
                         result_note_id: Optional[str], db: Session) -> Optional[dict]:
    """Sara checks her own output before reporting it (Phase 9.3).

    1. Concrete: if an artifact/note was produced, confirm it actually has content.
    2. Sanity: a fast A3B pass on (task, summary) -> SUCCESS/PARTIAL/FAILED, catching
       'reported done but the summary describes a failure' (and the inverse).
    """
    notes = []

    # 1. Artifact presence + non-triviality.
    if result_note_id:
        try:
            from sqlalchemy import text
            row = db.execute(text("SELECT length(coalesce(content,'')) FROM note WHERE id = :id"),
                             {"id": result_note_id}).first()
            if row is not None:
                n = int(row[0] or 0)
                notes.append(f"artifact has {n} chars" if n > 50 else f"artifact looks empty ({n} chars)")
        except Exception:
            pass

    # 2. Fast sanity check.
    try:
        import os, httpx
        url = os.getenv("FAST_MODEL_URL", "http://10.185.1.8:8686/v1")
        model = os.getenv("FAST_MODEL", "qwen3.6-35b-a3b")
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=2.0)) as c:
            r = await c.post(f"{url.rstrip('/')}/chat/completions", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Given a task and the agent's result summary, did the task actually succeed? Reply with ONE word: SUCCESS, PARTIAL, or FAILED."},
                    {"role": "user", "content": f"TASK: {task_query[:500]}\n\nRESULT: {result_summary[:800]}"}],
                "temperature": 0.0, "max_tokens": 4,
                "chat_template_kwargs": {"enable_thinking": False}})
            r.raise_for_status()
            v = (r.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip().upper()
            for tag in ("SUCCESS", "PARTIAL", "FAILED"):
                if tag in v:
                    notes.append(tag.lower())
                    break
    except Exception:
        pass

    return {"note": ", ".join(notes)} if notes else None


def _already_delivered(user_id: str, task_id: str, db: Session) -> bool:
    """Check the notification ledger for this task — no time window, told once is told forever."""
    try:
        from sqlalchemy import text
        row = db.execute(
            text("""
                SELECT 1 FROM notification_log
                WHERE user_id = :uid AND topic = :topic AND sent = true
                LIMIT 1
            """),
            {"uid": user_id, "topic": f"task_complete:{task_id}"},
        ).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"Ledger check failed (delivering anyway): {e}")
        return False


def _record_delivered(user_id: str, task_id: str, task_query: str, db: Session) -> None:
    """Write the tell-once ledger entry for this task completion."""
    try:
        from sqlalchemy import text
        db.execute(
            text("""
                INSERT INTO notification_log
                    (user_id, topic, category, title, message, priority, source, cooldown_hours, sent)
                VALUES
                    (:uid, :topic, 'agent_task', 'Background task complete', :msg,
                     'normal', 'task_result_delivery', 0, true)
            """),
            {
                "uid": user_id,
                "topic": f"task_complete:{task_id}",
                "msg": task_query[:500],
            },
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record delivery ledger entry: {e}")
        try:
            db.rollback()
        except Exception:
            pass


_LEAK_PATTERNS = (
    "let me create", "let me write", "now i have enough", "i'll create",
    "i'll now", "let's do this", "here's my plan", "i need to",
    "next, i will", "i'm going to",
)


def _looks_like_monologue(text: str) -> bool:
    """Cheap pre-filter: does this read like agent chain-of-thought rather
    than a finished deliverable? Used only to decide whether the summarize
    pass is worth the LLM call — the pass itself is authoritative."""
    head = (text or "")[:200].lower()
    return any(p in head for p in _LEAK_PATTERNS)


async def _summarize_for_delivery(task_query: str, raw_summary: str, note_title: Optional[str]) -> str:
    """Rewrite the agent's raw output into a short, David-facing summary:
    what was produced, where it lives, the one next action. Never returns
    the raw text on failure — falls back to a generic, unmistakably-safe
    line instead, because a leak is worse than a generic line."""
    safe_fallback = (
        f"Finished: {task_query[:100]}."
        + (f" Saved to '{note_title}'." if note_title else "")
    )
    if not raw_summary or not raw_summary.strip():
        return safe_fallback

    try:
        from app.core.llm import get_background_llm_client
        llm = get_background_llm_client()
        prompt = (
            "A background task just finished. Rewrite its raw output as a short, "
            "warm, David-facing summary in Sara's voice: what was produced, and (if "
            "relevant) the one next action. Never include planning language, "
            "first-person process narration (\"let me...\", \"I'll now...\", \"here's my "
            "plan\"), or meta-commentary about the task itself — only the substance. "
            "2-3 sentences max.\n\n"
            f"Task: {task_query[:200]}\n\n"
            f"Raw output:\n{raw_summary[:3000]}"
        )
        response = await llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=300,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        content = response["choices"][0]["message"].get("content", "").strip()
        if content:
            return content
    except Exception as e:
        logger.warning(f"Task result summarize pass failed (using safe fallback): {e}")

    # If the pre-filter thinks this is monologue and the LLM pass failed,
    # never fall through to the raw text — the generic line is the floor.
    if _looks_like_monologue(raw_summary):
        return safe_fallback
    return raw_summary


def _compose_chat_message(query: str, summary: str, note_title: Optional[str]) -> str:
    """Build a Sara-voice message for the completed task result."""
    parts = [f"Your background research is ready! Here's what I found:\n\n{summary}"]
    if note_title:
        parts.append(f"\nFull report saved to your workspace: **{note_title}**")
    return "\n".join(parts)


def _task_subject(query: str) -> str:
    """Short, David-facing task subject for the notification title (MINDV2
    Phase 0 / F3). Replaces the constant "Background task complete" title,
    which carried zero information about what actually finished."""
    subject = " ".join((query or "").split())
    if len(subject) > 60:
        subject = subject[:57].rstrip() + "..."
    return subject or "Background task"


def _push_body(summary: str) -> str:
    """Truncate the actual outcome summary for a push notification body
    (MINDV2 Phase 0 / F3). The body is the outcome — what was produced —
    not the original task query."""
    body = (summary or "").strip()
    if len(body) > 180:
        body = body[:177].rstrip() + "..."
    return body or "Finished — no summary available."


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


