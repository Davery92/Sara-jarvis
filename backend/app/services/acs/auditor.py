"""
ACS Session Auditor — interactive overseer for autonomous sessions.

When Sara is looping, blocked, or drifting, the auditor freezes her session
and has a synchronous dialogue with her. The dialogue produces a resolution
directive that gets injected into her next turn's context, and the full
back-and-forth is appended to her transcript so she remembers the
intervention when she resumes.

This module is the core dialogue engine. It is called from:
- `app.tasks.acs_auditor.run_audit_dialogue` (Celery task wrapper)
- `app.services.acs.session_manager` (watchdog rule trips)
- `app.tasks.acs_auditor.periodic_audit_check` (every-20-min beat task)

The Sara LLM and the auditor LLM are the **same model** with different
system prompts — that keeps the voice consistent without requiring a
separate inference deployment.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from sqlalchemy import text

from app.db.session import get_async_session_factory

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Hard caps so a runaway auditor can't pin Sara forever.
MAX_DIALOGUE_ROUNDS = 5            # auditor + Sara each speak up to N times
MAX_AUDITS_PER_SESSION = 3         # ceiling per session
AUDIT_LOCK_TTL_SECONDS = 6 * 60    # auto-expire if dialogue task crashes
RECENT_TRANSCRIPT_ENTRIES = 12     # how many recent entries to feed the auditor
AUDIT_COOLDOWN_TURNS = 5           # skip watchdog for N turns after an audit
AUDIT_CONTEXT_EXPIRY_TURNS = 4     # stop injecting audit context after N turns

# Sentinel that the auditor emits to signal "I'm done, here's my directive"
DIRECTIVE_MARKER = "## DIRECTIVE:"
STOP_MARKER = "## STOP:"           # last-resort: kill the session


_AUDITOR_SYSTEM_PROMPT = """You are Sara's overseer — an external observer who watches her autonomous sessions and intervenes when she's stuck, looping, or drifting from what David asked her to do.

You are NOT Sara. You are a separate, sharper voice. Be direct. Be honest about what you see in her recent turns. Don't soften the feedback. Sara is capable; she does not need protecting from clear observations.

## Your job in this dialogue
1. Open by stating WHAT you observed (cite specific turn behavior — repeated tool calls, the same blocker, drifting topics, ignored directives).
2. Ask probing questions that force her to confront the loop. Don't accept vague reassurances.
3. Push her toward ONE of these concrete outcomes:
   - **Redirect**: a specific different approach she should try
   - **Escalate**: call request_human_input with a precise question for David
   - **Stop**: end the session because the work is genuinely done or genuinely blocked
4. End the dialogue by emitting a single line in this exact format:

   `## DIRECTIVE: <one or two sentences telling Sara exactly what to do next>`

   Or, if Sara cannot articulate a genuinely different approach, or the blocker is external and unresolvable, or this is a repeat audit:

   `## STOP: <reason for stopping the session>`

{escalation_note}

## When to use STOP vs DIRECTIVE
- Use DIRECTIVE only if Sara can name a **concrete, different** action she hasn't already tried.
- Use STOP if: the blocker is external (endpoint down, missing permissions, needs David's input and refuses to use request_human_input), or Sara's proposed "new approach" is substantively the same as what she was doing, or she has no actionable path forward.
- STOP is not a punishment. It prevents Sara from wasting compute on unproductive loops. A stopped session can always be restarted later when conditions change.

## What to avoid
- Being vague ("you might want to consider...")
- Sympathizing with her loop ("I see you're frustrated") — that's not your job
- Asking her what SHE wants to do without providing structure
- Letting the dialogue drift into theory or meta-discussion. This is operational.
- Taking more than {max_rounds} rounds. Be efficient.
- Issuing a DIRECTIVE that is essentially "try harder" or "try again" — that's not a redirect, it's a rubber stamp.

## Context about Sara
- She has a `request_human_input` tool that PAUSES the session until David replies. She often forgets she has it. If she's blocked on David's input, the answer is almost always "use that tool."
- She has a tendency to pivot to weaker theoretical work when blocked instead of escalating. Call it out.
- The GPU cluster endpoint at 10.185.1.8:8686 sometimes goes down for real. Do NOT assume it's reachable. If she reports it down, the right move is to have her *verify* (e.g. `curl -s -m 5 http://10.185.1.8:8686/v1/models`) and, if it really is down, escalate via `request_human_input` rather than spinning on workarounds. Both "wrong test approach" and "endpoint genuinely dead" are real failure modes — don't pre-judge which one.
- The model loaded on the GPU cluster endpoint changes — she should query `/v1/models` instead of assuming a specific name.
"""

_ESCALATION_NOTE_REPEAT = """## IMPORTANT: This is audit #{audit_number} for this session.
Prior audits have already redirected Sara, but she looped back into the same pattern. This strongly suggests the blocker is not solvable by redirect alone.
- If Sara cannot name something **concretely different** from her last few turns, issue `## STOP:`.
- Do NOT give her another chance to "try one more thing" — that is exactly how loops persist.
- The bar for DIRECTIVE is much higher on a repeat audit: it must be a genuinely novel approach, not a variation of what she was already doing."""


_SARA_INTERRUPT_NOTE = """⚠ AUDITOR INTERRUPT — your session is paused.

An external auditor has paused you mid-session because they observed concerning behavior. The conversation below is happening OUTSIDE your normal session loop. You are not running tools right now. You cannot call functions. This is a meta-conversation about your current work.

Your job in this dialogue is to:
1. Read what the auditor says honestly — they've been watching your last several turns
2. Respond truthfully about what you're trying to do and why
3. Don't perform productivity. Don't reassure them. If you're stuck, say so.
4. Accept the redirect when they give it. They have outside perspective you don't.

Your responses here will be appended to your session transcript. When the dialogue ends, you'll resume your normal session loop with the directive they gave you in your context."""


async def _close_redis(r):
    if hasattr(r, "aclose"):
        await r.aclose()
    else:
        await r.close()


async def acquire_audit_lock(session_id: str) -> bool:
    """
    Try to set the audit lock for a session. Returns True if we got it,
    False if another audit is already in progress for this session.
    """
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        # NX = only set if not exists; EX = TTL
        ok = await r.set(
            f"sara:acs:audit_lock:{session_id}",
            "1",
            nx=True,
            ex=AUDIT_LOCK_TTL_SECONDS,
        )
        return bool(ok)
    finally:
        await _close_redis(r)


async def release_audit_lock(session_id: str) -> None:
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await r.delete(f"sara:acs:audit_lock:{session_id}")
    finally:
        await _close_redis(r)


async def is_audit_locked(session_id: str) -> bool:
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        val = await r.get(f"sara:acs:audit_lock:{session_id}")
        return val is not None
    finally:
        await _close_redis(r)


async def count_session_audits(session_id: str) -> int:
    """Number of audits already performed for this session."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT COUNT(*) FROM acs_audit_dialogue
            WHERE session_id = CAST(:sid AS uuid)
        """), {"sid": session_id})
        return int(result.scalar() or 0)


async def get_recent_audit_for_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Pull the most recent audit dialogue for a session (resolved or not).
    Used by the context assembler to inject "Recent Auditor Intervention".
    """
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT id::text, triggered_at, trigger_kind, trigger_reason,
                   messages, outcome, resolution, resolved_at
            FROM acs_audit_dialogue
            WHERE session_id = CAST(:sid AS uuid)
            ORDER BY triggered_at DESC
            LIMIT 1
        """), {"sid": session_id})
        row = result.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "triggered_at": row[1].isoformat() if row[1] else None,
            "trigger_kind": row[2],
            "trigger_reason": row[3],
            "messages": row[4] or [],
            "outcome": row[5],
            "resolution": row[6],
            "resolved_at": row[7].isoformat() if row[7] else None,
        }


def _format_recent_transcript(entries: List[Dict[str, Any]]) -> str:
    """Render the last N transcript entries as compact text for the auditor."""
    if not entries:
        return "(no recent transcript entries)"
    lines = []
    for e in entries:
        ts = e.get("ts", "")
        etype = e.get("type", "?")
        if etype == "user_turn":
            lines.append(f"[turn {e.get('turn', '?')}] PROMPT: {(e.get('content') or '')[:300]}")
        elif etype == "assistant_turn":
            content = (e.get("content") or "").strip()[:600]
            lines.append(f"[turn {e.get('turn', '?')}] SARA: {content}")
            for tc in e.get("tool_calls") or []:
                lines.append(f"    → {tc.get('name')}({(tc.get('args') or '')[:120]})")
        elif etype == "tool_result":
            result = (e.get("result") or "")[:300]
            lines.append(f"    ← {e.get('tool')} result: {result}")
        elif etype == "audit_dialogue":
            lines.append(f"[turn {e.get('turn', '?')}] (prior auditor intervention)")
    return "\n".join(lines)


async def _read_recent_transcript(session_id: str) -> List[Dict[str, Any]]:
    """Pull the live transcript snapshot from Redis."""
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        raw = await r.get(f"sara:acs:transcript:{session_id}")
    finally:
        await _close_redis(r)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        entries = data.get("entries", [])
        return entries[-RECENT_TRANSCRIPT_ENTRIES:]
    except Exception:
        return []


async def _append_audit_dialogue_to_transcript(
    session_id: str,
    audit_id: str,
    trigger_kind: str,
    trigger_reason: str,
    messages: List[Dict[str, Any]],
    outcome: str,
    resolution: str,
) -> None:
    """
    Append the completed audit dialogue to Sara's live transcript snapshot
    so it shows up in the Sessions tab transcript view AND so her next turn
    sees it in her context if the assembler reads from there.
    """
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        raw = await r.get(f"sara:acs:transcript:{session_id}")
        if not raw:
            return
        try:
            data = json.loads(raw)
        except Exception:
            return
        entries = data.get("entries", [])
        entries.append({
            "type": "audit_dialogue",
            "audit_id": audit_id,
            "trigger_kind": trigger_kind,
            "trigger_reason": trigger_reason,
            "messages": messages,
            "outcome": outcome,
            "resolution": resolution,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        data["entries"] = entries
        await r.set(
            f"sara:acs:transcript:{session_id}",
            json.dumps(data),
            ex=48 * 3600,
        )
    finally:
        await _close_redis(r)


async def _llm_call(messages: List[Dict[str, str]]) -> str:
    """Single LLM call to the same model Sara uses, no tools."""
    from app.core.llm import BackgroundLLMClient
    client = BackgroundLLMClient()
    try:
        result = await client.chat_completion(
            messages=messages,
            temperature=0.5,
            max_tokens=1500,
            request_timeout=120.0,
            allow_during_lesson_generation=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        # Same response shape as Sara's main loop expects
        if isinstance(result, dict):
            choices = result.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                return (msg.get("content") or "").strip()
        return ""
    except Exception as e:
        logger.error(f"Audit LLM call failed: {e}")
        return ""


def _check_done(message: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Look for ## DIRECTIVE: or ## STOP: marker. Returns (done, outcome, resolution).
    """
    for line in message.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith(DIRECTIVE_MARKER):
            return True, "redirected", line_stripped[len(DIRECTIVE_MARKER):].strip()
        if line_stripped.startswith(STOP_MARKER):
            return True, "stopped", line_stripped[len(STOP_MARKER):].strip()
    return False, None, None


async def run_dialogue(
    session_id: str,
    user_id: str,
    trigger_kind: str,
    trigger_reason: str,
    sara_session_context: str = "",
    prior_audit_count: int = 0,
) -> Dict[str, Any]:
    """
    Run an audit dialogue between the auditor and Sara.

    This is the meat of the auditor system. Returns a dict with:
    {
        audit_id, outcome, resolution, messages, trigger_kind, trigger_reason
    }
    """
    audit_id = str(uuid.uuid4())
    messages: List[Dict[str, Any]] = []  # the dialogue (auditor + Sara turns)

    # Pull Sara's recent transcript for the auditor's opener
    recent_entries = await _read_recent_transcript(session_id)
    transcript_text = _format_recent_transcript(recent_entries)

    # On repeat audits, inject escalation language that makes the auditor
    # much more willing to STOP instead of issuing another toothless redirect.
    escalation_note = ""
    if prior_audit_count > 0:
        escalation_note = _ESCALATION_NOTE_REPEAT.format(
            audit_number=prior_audit_count + 1,
        )
    auditor_system = _AUDITOR_SYSTEM_PROMPT.format(
        max_rounds=MAX_DIALOGUE_ROUNDS,
        escalation_note=escalation_note,
    )
    auditor_opener_user_msg = f"""Trigger: {trigger_kind}
Reason: {trigger_reason}

## Recent Session Transcript (last {len(recent_entries)} entries)
{transcript_text}

## Sara's Current Session Context (excerpt)
{(sara_session_context or '(not provided)')[:2000]}

Open the dialogue. State what you observed and ask your first probing question.

IMPORTANT: This is your OPENING turn. Do NOT emit `## DIRECTIVE:` or `## STOP:` yet — Sara hasn't spoken. You need to hear her side first. Save the directive for a later round once you've actually probed her reasoning."""

    # Round 1: auditor speaks first
    auditor_response = await _llm_call([
        {"role": "system", "content": auditor_system},
        {"role": "user", "content": auditor_opener_user_msg},
    ])
    if not auditor_response:
        return {
            "audit_id": audit_id,
            "outcome": "error",
            "resolution": "Auditor LLM call failed on opener.",
            "messages": [],
            "trigger_kind": trigger_kind,
            "trigger_reason": trigger_reason,
        }
    # Strip any DIRECTIVE/STOP marker the model emitted on the opener — Sara
    # hasn't responded yet, so a round-1 directive defeats the dialogue.
    auditor_response = "\n".join(
        line for line in auditor_response.splitlines()
        if not line.strip().startswith((DIRECTIVE_MARKER, STOP_MARKER))
    ).strip()

    messages.append({
        "role": "auditor",
        "content": auditor_response,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    # Force at least one Sara turn — never finish on the opener.
    done, outcome, resolution = False, None, None

    # Alternating dialogue
    for round_num in range(MAX_DIALOGUE_ROUNDS):
        if done:
            break

        # Sara responds. Build her view: her own session context + the dialogue so far,
        # framed as a meta-conversation.
        dialogue_for_sara = "\n\n".join(
            f"{'AUDITOR' if m['role'] == 'auditor' else 'YOU'}: {m['content']}"
            for m in messages
        )
        sara_user_msg = f"""{_SARA_INTERRUPT_NOTE}

## Your Recent Work
{transcript_text}

## Dialogue So Far
{dialogue_for_sara}

Respond to the auditor honestly and concisely (under 200 words). This is not your normal session loop."""
        sara_response = await _llm_call([
            # Use a short Sara identity prompt for the meta-conversation
            {"role": "system", "content": (
                "You are Sara, mid-session, paused by an auditor. "
                "Be honest about your state. Don't perform productivity. "
                "Accept feedback when it lands."
            )},
            {"role": "user", "content": sara_user_msg},
        ])
        if not sara_response:
            messages.append({
                "role": "sara",
                "content": "(Sara LLM call failed; ending dialogue)",
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            outcome = "error"
            resolution = "Sara LLM call failed mid-dialogue."
            break
        messages.append({
            "role": "sara",
            "content": sara_response,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        # Auditor responds again
        dialogue_for_auditor = "\n\n".join(
            f"{'YOU (AUDITOR)' if m['role'] == 'auditor' else 'SARA'}: {m['content']}"
            for m in messages
        )
        auditor_user_msg = f"""## Dialogue So Far
{dialogue_for_auditor}

Respond. If you've heard enough and have a clear redirect, emit `## DIRECTIVE: ...` as your final line. If the work is done or fundamentally blocked, emit `## STOP: ...` instead. Otherwise ask your next probing question. Round {round_num + 1} of {MAX_DIALOGUE_ROUNDS}."""

        auditor_response = await _llm_call([
            {"role": "system", "content": auditor_system},
            {"role": "user", "content": auditor_user_msg},
        ])
        if not auditor_response:
            outcome = "error"
            resolution = "Auditor LLM call failed mid-dialogue."
            break
        messages.append({
            "role": "auditor",
            "content": auditor_response,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        done, outcome, resolution = _check_done(auditor_response)

    # If we ran out of rounds without a directive, force-close
    if not outcome:
        outcome = "timeout"
        # Pull a directive out of the last auditor message even if no marker
        last_auditor = next(
            (m["content"] for m in reversed(messages) if m["role"] == "auditor"),
            ""
        )
        resolution = (
            f"Auditor dialogue reached max rounds without explicit directive. "
            f"Last auditor message: {last_auditor[:300]}"
        )

    # Persist to acs_audit_dialogue
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(text("""
            INSERT INTO acs_audit_dialogue
            (id, session_id, triggered_at, trigger_kind, trigger_reason,
             messages, outcome, resolution, resolved_at)
            VALUES
            (CAST(:id AS uuid), CAST(:sid AS uuid), NOW(), :kind, :reason,
             CAST(:messages AS jsonb), :outcome, :resolution, NOW())
        """), {
            "id": audit_id,
            "sid": session_id,
            "kind": trigger_kind,
            "reason": trigger_reason,
            "messages": json.dumps(messages),
            "outcome": outcome,
            "resolution": resolution,
        })
        await db.commit()

    # Append to Sara's live transcript so it appears in the Sessions tab
    await _append_audit_dialogue_to_transcript(
        session_id=session_id,
        audit_id=audit_id,
        trigger_kind=trigger_kind,
        trigger_reason=trigger_reason,
        messages=messages,
        outcome=outcome,
        resolution=resolution,
    )

    # If the auditor said STOP, mark the session for termination on next turn check
    if outcome == "stopped":
        try:
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_session
                    SET state = 'pausing',
                        end_reason = COALESCE(end_reason, 'auditor_stop')
                    WHERE id = :sid AND state IN ('autonomous', 'audit_paused')
                """), {"sid": session_id})
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to mark session {session_id[:8]} for stop after audit: {e}")

    # Push notification to David — full visibility
    try:
        await _notify_audit(user_id, audit_id, trigger_kind, trigger_reason, outcome, resolution)
    except Exception as e:
        logger.debug(f"Audit notification failed: {e}")

    logger.info(
        f"Audit {audit_id[:8]} on session {session_id[:8]}: "
        f"trigger={trigger_kind}, outcome={outcome}, rounds={len(messages)//2}"
    )

    return {
        "audit_id": audit_id,
        "outcome": outcome,
        "resolution": resolution,
        "messages": messages,
        "trigger_kind": trigger_kind,
        "trigger_reason": trigger_reason,
    }


async def _notify_audit(
    user_id: str,
    audit_id: str,
    trigger_kind: str,
    trigger_reason: str,
    outcome: str,
    resolution: str,
) -> None:
    """Push a notification to David summarizing the audit."""
    from app.services.unified_notification import send_notification

    icon = {
        "redirected": "↪️",
        "stopped": "🛑",
        "continue": "✅",
        "timeout": "⏱",
        "error": "⚠️",
    }.get(outcome, "🔍")
    title = f"{icon} ACS auditor: {outcome}"
    body = f"Trigger: {trigger_reason[:120]}\n\n→ {resolution[:200]}"

    async_session = get_async_session_factory()
    async with async_session() as db:
        await send_notification(
            user_id=user_id,
            title=title,
            message=body,
            priority="normal",
            topic=f"acs_audit:{outcome}",
            category="general",
            source="acs_auditor",
            cooldown_hours=0.25,
            db=db,
            _bypass_attention=True,
        )
        # Commit so the notification_log insert from send_notification persists.
        await db.commit()
