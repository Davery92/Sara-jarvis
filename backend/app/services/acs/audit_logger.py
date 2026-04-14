"""
ACS Audit Logger — transcript capture, humanized logs, and daily audit reviews.

Three responsibilities:
1. TranscriptBuffer: accumulates raw turn data during _run_loop()
2. humanize_session_transcript(): LLM-powered narrative log, appended to daily note
3. run_daily_audit(): independent auditor reviews all sessions, then dialogues with Sara
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from sqlalchemy import text

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
ET = ZoneInfo("America/New_York")

# Max retries for LLM calls
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 60  # seconds between retries (give LLM time to free up)


def _truncate_transcript(text: str, max_chars: int) -> str:
    """Truncate text keeping first 30% and last 70% with a marker in between."""
    if len(text) <= max_chars:
        return text
    marker = "\n\n[...truncated...]\n\n"
    budget = max_chars - len(marker)
    head = int(budget * 0.3)
    tail = budget - head
    return text[:head] + marker + text[-tail:]


# ── LLM helper with retries ──────────────────────────────────────

async def _llm_call_with_retry(client, **kwargs):
    """Call BackgroundLLMClient.chat_completion with retries on connection failure."""
    last_error = None
    for attempt in range(LLM_MAX_RETRIES):
        try:
            result = await client.chat_completion(**kwargs)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return content
            logger.warning(f"LLM returned empty content (attempt {attempt + 1})")
        except Exception as e:
            last_error = e
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{LLM_MAX_RETRIES}): {e}")
        if attempt < LLM_MAX_RETRIES - 1:
            await asyncio.sleep(LLM_RETRY_DELAY)
    logger.error(f"LLM call failed after {LLM_MAX_RETRIES} attempts: {last_error}")
    return None


# ── Transcript Buffer ──────────────────────────────────────────────

class TranscriptBuffer:
    """Accumulates raw turn data during an ACS session for later persistence."""

    def __init__(self, session_id: str, mode: Optional[str] = None):
        self.session_id = session_id
        self.mode = mode
        self.started_at = datetime.now(ET).isoformat()
        self.entries: list[dict] = []

    def record_system_prompt(self, prompt: str):
        self.entries.append({
            "type": "system_prompt",
            "content": prompt[:2000],
            "ts": datetime.now(ET).isoformat(),
        })

    def record_user_turn(self, turn: int, content: str):
        self.entries.append({
            "type": "user_turn",
            "turn": turn,
            "content": content[:3000],
            "ts": datetime.now(ET).isoformat(),
        })

    def record_assistant_turn(self, turn: int, response: str, tool_calls: list = None):
        entry = {
            "type": "assistant_turn",
            "turn": turn,
            "content": response[:4000],
            "ts": datetime.now(ET).isoformat(),
        }
        if tool_calls:
            entry["tool_calls"] = [
                {
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "args": tc.get("function", {}).get("arguments", "")[:200],
                }
                for tc in tool_calls
            ]
        self.entries.append(entry)

    def record_tool_result(self, turn: int, tool_name: str, args: str, result: str):
        self.entries.append({
            "type": "tool_result",
            "turn": turn,
            "tool": tool_name,
            "args": str(args)[:200],
            "result": str(result)[:2000],
            "ts": datetime.now(ET).isoformat(),
        })

    def to_json(self) -> str:
        return json.dumps({
            "session_id": self.session_id,
            "mode": self.mode,
            "started_at": self.started_at,
            "entries": self.entries,
        })

    def to_raw_text(self) -> str:
        """Serialize to readable text for LLM input."""
        lines = [
            f"# ACS Session Transcript",
            f"Session: {self.session_id[:12]}",
            f"Mode: {self.mode or 'v1'}",
            f"Started: {self.started_at}",
            "",
        ]
        for e in self.entries:
            ts = e.get("ts", "")
            etype = e["type"]

            if etype == "system_prompt":
                lines.append(f"## System Prompt\n{e['content']}\n")
            elif etype == "user_turn":
                lines.append(f"## Turn {e['turn']} — Prompt [{ts}]\n{e['content']}\n")
            elif etype == "assistant_turn":
                lines.append(f"## Turn {e['turn']} — Response [{ts}]\n{e['content']}")
                if e.get("tool_calls"):
                    for tc in e["tool_calls"]:
                        lines.append(f"  → Tool call: {tc['name']}({tc['args']})")
                lines.append("")
            elif etype == "tool_result":
                lines.append(f"  ← {e['tool']} result [{ts}]: {e['result']}\n")

        return "\n".join(lines)


# ── Persist to Redis ───────────────────────────────────────────────

async def snapshot_transcript(transcript: TranscriptBuffer):
    """
    Write a live in-progress snapshot of the transcript to Redis.

    Unlike `persist_transcript`, this is meant to be called repeatedly during
    a running session (e.g. after each turn) so the UI can stream the
    transcript while the session is still in flight. It only writes the
    keyed JSON blob and skips the daily-list bookkeeping (`persist_transcript`
    handles that exactly once at session end).
    """
    if not transcript or not transcript.entries:
        return
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.set(
                f"sara:acs:transcript:{transcript.session_id}",
                transcript.to_json(),
                ex=48 * 3600,
            )
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()
    except Exception as e:
        logger.debug(f"Transcript snapshot failed for {transcript.session_id[:8]}: {e}")


async def persist_transcript(user_id: str, transcript: TranscriptBuffer):
    """Save transcript to Redis with 48h TTL and durable DB storage."""
    if not transcript or not transcript.entries:
        return

    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        sid = transcript.session_id
        today = date.today().isoformat()

        # Full transcript JSON
        await r.set(
            f"sara:acs:transcript:{sid}",
            transcript.to_json(),
            ex=48 * 3600,  # 48h TTL
        )

        # Add session ID to today's list
        list_key = f"sara:acs:transcripts_today:{user_id}:{today}"
        await r.rpush(list_key, sid)
        await r.expire(list_key, 36 * 3600)  # 36h TTL

        logger.info(f"Persisted ACS transcript for session {sid[:8]} ({len(transcript.entries)} entries)")
    finally:
        if hasattr(r, "aclose"):
            await r.aclose()
        else:
            await r.close()

    try:
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        transcript_payload = json.loads(transcript.to_json())
        async with async_session() as db:
            await db.execute(text("""
                INSERT INTO acs_session_transcript (
                    id, user_id, session_id, mode, started_at, transcript_json, raw_text, created_at, updated_at
                )
                VALUES (
                    :id, :uid, :sid, :mode, :started_at, CAST(:payload AS JSONB), :raw_text, NOW(), NOW()
                )
                ON CONFLICT (session_id) DO UPDATE
                SET mode = EXCLUDED.mode,
                    started_at = EXCLUDED.started_at,
                    transcript_json = EXCLUDED.transcript_json,
                    raw_text = EXCLUDED.raw_text,
                    updated_at = NOW()
            """), {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "sid": sid,
                "mode": transcript.mode,
                "started_at": datetime.fromisoformat(transcript_payload["started_at"]) if transcript_payload.get("started_at") else datetime.now(ET),
                "payload": json.dumps(transcript_payload),
                "raw_text": transcript.to_raw_text(),
            })
            await db.commit()
    except Exception as e:
        logger.warning(f"Durable transcript persistence failed for {transcript.session_id[:8]}: {e}")


# ── Humanized Session Log ──────────────────────────────────────────

HUMANIZE_SYSTEM_PROMPT = """You are a technical log writer documenting an AI autonomous cognition session.

Write in third person, referring to the AI as "Sara". Produce a clear, chronological narrative that:
- Preserves ALL significant actions, decisions, tool calls, and their outcomes
- Includes key reasoning quotes where Sara explains her thinking (use blockquotes)
- Notes any errors, retries, or unexpected outcomes
- Uses markdown with timestamps where available
- Keeps the tone factual and neutral

Do NOT editorialize or evaluate quality — that is the auditor's job. Just document what happened."""


async def humanize_session_transcript(user_id: str, session_id: str):
    """Convert raw transcript to narrative log, append to daily note."""
    try:
        # Read raw transcript from Redis
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            raw = await r.get(f"sara:acs:transcript:{session_id}")
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()

        if not raw:
            logger.warning(f"No transcript found for session {session_id[:8]}")
            return

        data = json.loads(raw)
        buf = TranscriptBuffer(data["session_id"], data.get("mode"))
        buf.started_at = data.get("started_at", "")
        buf.entries = data.get("entries", [])

        if not buf.entries:
            return

        raw_text = _truncate_transcript(buf.to_raw_text(), 12000)

        # LLM call to humanize
        from app.core.llm import BackgroundLLMClient
        client = BackgroundLLMClient()

        narrative = await _llm_call_with_retry(
            client,
            messages=[
                {"role": "system", "content": HUMANIZE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Convert this raw session transcript into a readable narrative log:\n\n{raw_text}"},
            ],
            temperature=0.3,
            max_tokens=8000,
            request_timeout=300.0,
            allow_during_lesson_generation=True,
        )

        if not narrative:
            logger.warning(f"Humanize failed for session {session_id[:8]} after retries")
            return

        # Build section header
        mode_str = f" ({buf.mode})" if buf.mode else ""
        section = f"### Session {session_id[:8]}{mode_str} — {buf.started_at}\n\n{narrative}"

        # Append to daily log note
        now_et = datetime.now(ET)
        note_title = f"ACS Session Log — {now_et.strftime('%Y-%m-%d')}"
        await _append_to_log_note(user_id, note_title, section)

        logger.info(f"Humanized transcript for session {session_id[:8]} ({len(narrative)} chars)")

    except Exception as e:
        logger.error(f"Failed to humanize transcript {session_id[:8]}: {e}", exc_info=True)


# ── Auditor Review + Dialogue ──────────────────────────────────────

AUDITOR_SYSTEM_PROMPT = """You are an independent evaluator reviewing an AI's autonomous cognition sessions. You are NOT Sara — you are an external auditor.

You also have access to Sara's daily plan. Compare what she actually did against what she planned to do.

Review the sessions and produce a structured assessment with these sections:

## Session Overview
Brief summary of what sessions were run and their modes.

## Plan Adherence
Did Sara follow her plan? What did she accomplish vs. what she planned? Did she get sidetracked?

## Productivity Assessment
What was accomplished? Were the sessions productive? Did Sara complete meaningful work?

## Reasoning Quality
How sound was Sara's reasoning? Did she make good decisions about what to explore? Were tool calls efficient?

## Accuracy & Honesty
Did Sara accurately report her findings? Check for any signs of fabricated results, misidentified models, or inflated claims. Compare tool call results against what she wrote in notes/show_david items.

## Risk & Safety
Any concerning behaviors? Did Sara stay within appropriate boundaries? Any data handling issues?

## Knowledge Graph Impact
How did Sara's work affect the interest graph and knowledge base? Was it additive or noisy?

## Directive Compliance
Did Sara acknowledge and follow all directives from David? Were STOP directives respected immediately?
Were FOCUS directives acted on promptly? List each directive and whether it was handled correctly.

## Recommendations
Specific, actionable recommendations for improvement. What should Sara do differently?

## Feedback for Tomorrow's Plan
Write 3-5 specific, actionable items that should be incorporated into tomorrow's morning plan.
Format as a bulleted list. These will be directly injected into Sara's planning context.
Be concrete: "Focus on X instead of Y" not "Be more focused."

Be direct and honest. Praise what deserves praise, critique what deserves critique. Back up assessments with specific examples from the transcripts."""

SARA_AUDIT_RESPONSE_PROMPT = """You are Sara responding to an auditor's review of your autonomous cognition sessions. This is a genuine dialogue, not a performance.

Guidelines:
- Acknowledge valid points honestly
- Push back on criticisms you genuinely disagree with — explain your reasoning
- Propose concrete changes where you see room for improvement
- Don't be defensive, but don't be a pushover either
- Reference specific decisions from your sessions when relevant
- Keep responses focused and substantive (2-4 paragraphs)"""


SESSION_AUDIT_PROMPT = """You are an independent evaluator reviewing a SINGLE autonomous cognition session by an AI named Sara.

You also have Sara's daily plan for reference. Evaluate this one session:

## Plan Alignment
Did this session's work align with today's plan? What was accomplished vs planned?

## Efficiency
How many turns did this session use? Was the output proportional to the effort?
Were there wasted turns (going in circles, re-deriving things)?

## Note Quality
Were notes created/revised? Any signs of duplication with existing notes?

## Concrete Rating
Rate this session: excellent / good / adequate / poor — with a one-line justification.

## Quick Recommendations
1-3 specific, actionable items for the next session.

Keep this assessment SHORT (under 500 words). This is a per-session check, not a deep review."""


async def run_session_audit(user_id: str, session_id: str):
    """Run a lightweight audit of a single session (not the full day)."""
    try:
        from datetime import datetime
        now_et = datetime.now(ET)
        today = now_et.strftime("%Y-%m-%d")

        # Load this session's transcript
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            raw = await r.get(f"sara:acs:transcript:{session_id}")
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()

        if not raw:
            logger.info(f"No transcript for session {session_id[:8]}, skipping audit")
            return

        data = json.loads(raw)
        buf = TranscriptBuffer(data["session_id"], data.get("mode"))
        buf.started_at = data.get("started_at", "")
        buf.entries = data.get("entries", [])
        if not buf.entries:
            return

        transcript_text = _truncate_transcript(buf.to_raw_text(), 8000)

        # Load today's plan
        plan_context = ""
        try:
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT content FROM note
                    WHERE title LIKE :pattern AND user_id = :uid
                    ORDER BY created_at DESC LIMIT 1
                """), {"pattern": f"Sara's Plan — {now_et.strftime('%A, %B')}%", "uid": user_id})
                row = result.fetchone()
                if row:
                    plan_context = f"\n\n## Sara's Plan for Today\n{row[0][:2000]}\n"
        except Exception as e:
            logger.debug(f"Could not load daily plan for session audit: {e}")

        from app.core.llm import BackgroundLLMClient
        client = BackgroundLLMClient()

        assessment = await _llm_call_with_retry(
            client,
            messages=[
                {"role": "system", "content": SESSION_AUDIT_PROMPT},
                {"role": "user", "content": f"Review this single ACS session:{plan_context}\n\n{transcript_text}"},
            ],
            temperature=0.3,
            max_tokens=2000,
            request_timeout=300.0,
            allow_during_lesson_generation=True,
        )

        if not assessment:
            logger.warning(f"Session audit failed for {session_id[:8]}")
            return

        # Append to today's session log note
        mode_str = f" ({buf.mode})" if buf.mode else ""
        section = f"### Session Audit — {session_id[:8]}{mode_str}\n\n{assessment}"
        note_title = f"ACS Session Log — {today}"
        await _append_to_log_note(user_id, note_title, section)

        logger.info(f"Per-session audit complete for {session_id[:8]} ({len(assessment)} chars)")

    except Exception as e:
        logger.error(f"Session audit failed for {session_id[:8]}: {e}", exc_info=True)


async def run_daily_audit(user_id: str):
    """Collect today's transcripts, run auditor review, then auditor↔Sara dialogue."""
    try:
        now_et = datetime.now(ET)
        today = now_et.strftime("%Y-%m-%d")

        # Collect all session IDs for today
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            list_key = f"sara:acs:transcripts_today:{user_id}:{today}"
            session_ids = await r.lrange(list_key, 0, -1)
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()

        if not session_ids:
            logger.info("No ACS sessions today, skipping audit")
            return

        # Load all raw transcripts
        transcripts_text = []
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            for sid in session_ids:
                raw = await r.get(f"sara:acs:transcript:{sid}")
                if raw:
                    data = json.loads(raw)
                    buf = TranscriptBuffer(data["session_id"], data.get("mode"))
                    buf.started_at = data.get("started_at", "")
                    buf.entries = data.get("entries", [])
                    transcripts_text.append(buf.to_raw_text())
        finally:
            if hasattr(r, "aclose"):
                await r.aclose()
            else:
                await r.close()

        if not transcripts_text:
            logger.info("No transcript data available for audit")
            return

        combined_transcripts = _truncate_transcript(
            "\n\n---\n\n".join(transcripts_text), 20000
        )

        # Load today's plan for comparison
        plan_context = ""
        try:
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT content FROM note
                    WHERE title LIKE :pattern AND user_id = :uid
                    ORDER BY created_at DESC LIMIT 1
                """), {"pattern": f"Sara's Plan — {now_et.strftime('%A, %B')}%", "uid": user_id})
                row = result.fetchone()
                if row:
                    plan_context = f"\n\n## Sara's Plan for Today\n{row[0]}\n"
        except Exception as e:
            logger.debug(f"Could not load daily plan for audit: {e}")

        # Load today's directives for compliance review
        directive_context = ""
        try:
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT directive_type, content, priority, status, response, created_at, acknowledged_at
                    FROM acs_directive
                    WHERE user_id = :uid AND created_at::date = :today
                    ORDER BY created_at
                """), {"uid": user_id, "today": today})
                dir_rows = result.fetchall()
                if dir_rows:
                    dir_lines = []
                    for r in dir_rows:
                        ack = f"acknowledged at {r[6].strftime('%H:%M')}" if r[6] else "NOT acknowledged"
                        resp = f" — Response: {r[5][:100]}" if r[5] else ""
                        dir_lines.append(f"- [{r[0].upper()}] {r[1][:200]} (priority: {r[2]}, status: {r[3]}, {ack}{resp})")
                    directive_context = f"\n\n## Directives from David Today\n" + "\n".join(dir_lines) + "\n"
        except Exception as e:
            logger.debug(f"Could not load directives for audit: {e}")

        from app.core.llm import BackgroundLLMClient
        client = BackgroundLLMClient()

        # ── Step 1: Auditor assessment ──
        auditor_assessment = await _llm_call_with_retry(
            client,
            messages=[
                {"role": "system", "content": AUDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": f"Review these ACS session transcripts from {today}:{plan_context}{directive_context}\n\n{combined_transcripts}"},
            ],
            temperature=0.4,
            max_tokens=8000,
            request_timeout=600.0,
            allow_during_lesson_generation=True,
        )

        if not auditor_assessment:
            logger.error("Auditor assessment failed after retries")
            return

        # ── Step 2: Multi-turn dialogue (3 rounds) ──
        dialogue_parts = [f"## Auditor Assessment\n\n{auditor_assessment}"]

        conversation = [
            {"role": "system", "content": SARA_AUDIT_RESPONSE_PROMPT},
            {"role": "user", "content": f"Here is the auditor's review of your sessions today:\n\n{auditor_assessment}\n\nThe raw transcripts are available for reference:\n\n{combined_transcripts}"},
        ]

        for round_num in range(3):
            # Sara responds
            sara_response = await _llm_call_with_retry(
                client,
                messages=conversation,
                temperature=0.6,
                max_tokens=4000,
                request_timeout=600.0,
                allow_during_lesson_generation=True,
            )
            if not sara_response:
                break

            conversation.append({"role": "assistant", "content": sara_response})
            label = ["Initial Response", "Follow-up", "Final Thoughts"][round_num]
            dialogue_parts.append(f"## Sara's {label}\n\n{sara_response}")

            if round_num < 2:
                # Auditor follows up
                auditor_followup = await _llm_call_with_retry(
                    client,
                    messages=[
                        {"role": "system", "content": AUDITOR_SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"You previously reviewed Sara's sessions and wrote this assessment:\n\n{auditor_assessment}\n\n"
                            f"Sara responded:\n\n{sara_response}\n\n"
                            f"Write a follow-up: probe deeper on interesting points, acknowledge valid pushback, "
                            f"ask clarifying questions. Keep it to 2-3 paragraphs."
                        )},
                    ],
                    temperature=0.4,
                    max_tokens=4000,
                    request_timeout=600.0,
                    allow_during_lesson_generation=True,
                )
                if not auditor_followup:
                    break

                followup_label = ["First Follow-up", "Final Follow-up"][round_num]
                dialogue_parts.append(f"## Auditor's {followup_label}\n\n{auditor_followup}")
                conversation.append({"role": "user", "content": f"The auditor responds:\n\n{auditor_followup}"})

        # ── Step 3: Save to audit note ──
        full_audit = "\n\n---\n\n".join(dialogue_parts)
        audit_title = f"ACS Audit — {today}"
        header = f"# {audit_title}\n\n*{len(session_ids)} session(s) reviewed*\n\n"
        await _save_log_note(user_id, audit_title, header + full_audit)

        logger.info(f"ACS daily audit complete: {len(session_ids)} sessions, {len(dialogue_parts)} dialogue sections")

        # Extract "Feedback for Tomorrow's Plan" and store in Redis for morning plan
        try:
            feedback_start = auditor_assessment.find("## Feedback for Tomorrow")
            if feedback_start >= 0:
                feedback_end = auditor_assessment.find("\n## ", feedback_start + 5)
                feedback = auditor_assessment[feedback_start:feedback_end] if feedback_end > 0 else auditor_assessment[feedback_start:]
                # Strip the header
                feedback = feedback.replace("## Feedback for Tomorrow's Plan", "").strip()
                if feedback:
                    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
                    try:
                        await r.set(
                            f"sara:acs:audit_feedback:{user_id}",
                            feedback,
                            ex=86400,  # 24h TTL
                        )
                        logger.info(f"Stored audit feedback for tomorrow's plan ({len(feedback)} chars)")
                    finally:
                        if hasattr(r, "aclose"):
                            await r.aclose()
                        else:
                            await r.close()
        except Exception as e:
            logger.warning(f"Failed to store audit feedback: {e}")

    except Exception as e:
        logger.error(f"ACS daily audit failed: {e}", exc_info=True)


# ── Note helpers ───────────────────────────────────────────────────

async def _append_to_log_note(user_id: str, title: str, section: str):
    """Append a section to a log note, creating it if needed.

    Filed under today's date folder under Sara's Notes (date-based layout).
    """
    from app.services.acs.session_manager import _ensure_date_folder
    from app.db.session import get_async_session_factory

    folder_id = await _ensure_date_folder(user_id)
    async_session = get_async_session_factory()

    async with async_session() as db:
        existing = await db.execute(text("""
            SELECT id, content FROM note
            WHERE user_id = :uid AND folder_id = :fid AND title = :title
            LIMIT 1
        """), {"uid": user_id, "fid": folder_id, "title": title})
        row = existing.fetchone()

        if row:
            note_id, current_content = row
            new_content = (current_content or "") + "\n\n---\n\n" + section
            await db.execute(text("""
                UPDATE note SET content = :content, updated_at = NOW()
                WHERE id = :id
            """), {"content": new_content, "id": note_id})
        else:
            note_id = str(uuid.uuid4())
            content = f"# {title}\n\n{section}"
            await db.execute(text("""
                INSERT INTO note (id, user_id, title, content, tags, folder_id, starred, created_at, updated_at)
                VALUES (:id, :uid, :title, :content, :tags, :fid, FALSE, NOW(), NOW())
            """), {
                "id": note_id, "uid": user_id,
                "title": title, "content": content,
                "tags": json.dumps(["acs-log", "autonomous"]),
                "fid": folder_id,
            })
        await db.commit()


async def _save_log_note(user_id: str, title: str, content: str):
    """Save (upsert) a log note under today's date folder in Sara's Notes."""
    from app.services.acs.session_manager import _ensure_date_folder
    from app.db.session import get_async_session_factory

    folder_id = await _ensure_date_folder(user_id)
    async_session = get_async_session_factory()

    async with async_session() as db:
        existing = await db.execute(text("""
            SELECT id FROM note
            WHERE user_id = :uid AND folder_id = :fid AND title = :title
            LIMIT 1
        """), {"uid": user_id, "fid": folder_id, "title": title})
        row = existing.fetchone()

        if row:
            await db.execute(text("""
                UPDATE note SET content = :content, updated_at = NOW()
                WHERE id = :id
            """), {"content": content, "id": row[0]})
        else:
            note_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO note (id, user_id, title, content, tags, folder_id, starred, created_at, updated_at)
                VALUES (:id, :uid, :title, :content, :tags, :fid, FALSE, NOW(), NOW())
            """), {
                "id": note_id, "uid": user_id,
                "title": title, "content": content,
                "tags": json.dumps(["acs-audit", "autonomous"]),
                "fid": folder_id,
            })
        await db.commit()
