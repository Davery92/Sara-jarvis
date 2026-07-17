"""
Consolidation Engine — Sara's deep reflection and pattern recognition.

Runs 2x daily (afternoon ~2 PM, evening ~9 PM):
- Reviews 12h of observations and deliberation history
- Notices cross-day patterns
- Calibrates salience weights based on what actually mattered
- Updates Sara's emotional arc
- Writes genuine reflective journal entries
- Extracts personal knowledge for PKG

This replaces the "deep run" concept (every 4th unified agent cycle).

Usage:
    from app.services.consolidation import consolidation_engine
    result = await consolidation_engine.run(user_id)
"""

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
USER_TZ = ZoneInfo("America/New_York")


@dataclass
class ConsolidationResult:
    patterns_noticed: List[str] = field(default_factory=list)
    calibration_notes: List[str] = field(default_factory=list)
    thread_updates: List[Dict] = field(default_factory=list)
    emotional_arc: str = ""
    journal_entry: str = ""
    salience_adjustments: Dict[str, float] = field(default_factory=dict)
    pkg_extractions: List[Dict] = field(default_factory=list)
    research_proposals: List[str] = field(default_factory=list)
    raw_response: str = ""
    duration_seconds: float = 0.0


class ConsolidationEngine:
    """Deep reflection engine: reviews the day so far, finds patterns, calibrates."""

    def __init__(self):
        self._llm_client = None

    def _get_llm_client(self):
        if self._llm_client is None:
            from app.core.llm import get_background_llm_client
            self._llm_client = get_background_llm_client()
        return self._llm_client

    async def run(self, user_id: str = DEFAULT_USER_ID) -> ConsolidationResult:
        """
        Run a consolidation cycle.
        1. Gather 12h of context (deliberation history, journal entries, observations)
        2. Read working memory for current state
        3. Full LLM call with larger context budget
        4. Parse and return results
        """
        start_time = datetime.now(timezone.utc)
        result = ConsolidationResult()

        # 1. Gather context
        context = await self._gather_context(user_id)

        # 2. Read working memory
        from app.services.working_memory import read_memory
        memory = await read_memory(user_id)

        # 3. Build prompt
        system_msg, user_msg = self._build_prompt(memory, context)

        # 4. LLM call
        try:
            client = self._get_llm_client()
            response = await client.chat_completion(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.6,
                max_tokens=2000,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            # Extract content from OpenAI-compatible response
            raw = ""
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices:
                    raw = choices[0].get("message", {}).get("content", "")
            else:
                raw = str(response)
            result.raw_response = raw

        except Exception as e:
            logger.error(f"[Consolidation] LLM call failed: {e}")
            result.journal_entry = f"Consolidation failed: {e}"
            result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            return result

        # 5. Parse
        try:
            parsed = self._parse_response(raw)
            result.patterns_noticed = parsed.get("patterns_noticed", [])
            result.calibration_notes = parsed.get("calibration_notes", [])
            result.emotional_arc = parsed.get("emotional_arc", "")
            result.journal_entry = parsed.get("journal_entry", "")
            result.salience_adjustments = parsed.get("salience_adjustments", {})
            result.pkg_extractions = parsed.get("pkg_extractions", [])
            result.research_proposals = [
                rp.strip() for rp in parsed.get("research_proposals", [])
                if isinstance(rp, str) and rp.strip()
            ]
        except Exception as e:
            logger.error(f"[Consolidation] Parse failed: {e}")
            result.journal_entry = f"Parse failed: {e}"

        result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()

        # 6. Apply results
        await self._apply_results(user_id, result)

        logger.info(
            f"[Consolidation] Complete in {result.duration_seconds:.1f}s: "
            f"{len(result.patterns_noticed)} patterns, "
            f"{len(result.pkg_extractions)} PKG extractions, "
            f"{len(result.research_proposals)} research proposals"
        )
        return result

    async def _gather_context(self, user_id: str) -> dict:
        """Gather 12 hours of deliberation history, journal entries, etc."""
        context = {
            "deliberation_history": [],
            "journal_entries": [],
            "notification_log": [],
            "notification_engagement": [],
            "pkg_interests": [],
            "recent_chat_topics": [],
        }

        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        try:
            async with async_session() as db:
                since = datetime.now(timezone.utc) - timedelta(hours=12)

                # Recent deliberation/agent run logs
                try:
                    rows = await db.execute(text("""
                        SELECT source, context_summary, handoff_note, watching_for, actions_taken, run_at
                        FROM agent_run_log
                        WHERE user_id = :uid AND run_at >= :since
                        ORDER BY run_at DESC LIMIT 20
                    """), {"uid": user_id, "since": since})
                    for row in rows.fetchall():
                        context["deliberation_history"].append({
                            "source": row.source,
                            "thought": row.context_summary[:300] if row.context_summary else "",
                            "handoff": row.handoff_note[:200] if row.handoff_note else "",
                            "watching": row.watching_for[:100] if row.watching_for else "",
                            "at": row.run_at.isoformat() if row.run_at else "",
                        })
                except Exception as e:
                    logger.debug(f"[Consolidation] Deliberation history query failed: {e}")

                # Recent journal entries
                try:
                    rows = await db.execute(text("""
                        SELECT content, entry_type, label, created_at
                        FROM sara_journal
                        WHERE user_id = :uid AND created_at >= :since
                        ORDER BY created_at DESC LIMIT 15
                    """), {"uid": user_id, "since": since})
                    for row in rows.fetchall():
                        context["journal_entries"].append({
                            "content": row.content[:300] if row.content else "",
                            "type": row.entry_type,
                            "label": row.label,
                            "at": row.created_at.isoformat() if row.created_at else "",
                        })
                except Exception as e:
                    logger.debug(f"[Consolidation] Journal query failed: {e}")

                # Notification log (what was sent, with feedback data)
                try:
                    rows = await db.execute(text("""
                        SELECT title, topic, category, sent_at, sent,
                               read_at, engaged, dismissed_at
                        FROM notification_log
                        WHERE user_id = :uid AND sent_at >= :since
                        ORDER BY sent_at DESC LIMIT 20
                    """), {"uid": user_id, "since": since})
                    for row in rows.fetchall():
                        outcome = "deduped"
                        if row.sent:
                            if row.engaged:
                                outcome = "engaged"
                            elif row.dismissed_at is not None:
                                outcome = "dismissed"
                            elif row.read_at is not None:
                                outcome = "read"
                            else:
                                outcome = "sent (no feedback)"
                        context["notification_log"].append({
                            "title": row.title,
                            "topic": row.topic,
                            "category": row.category or "general",
                            "sent": row.sent,
                            "outcome": outcome,
                            "at": row.sent_at.isoformat() if row.sent_at else "",
                        })
                except Exception as e:
                    logger.debug(f"[Consolidation] Notification log query failed: {e}")

                # Notification engagement stats (last 7 days)
                try:
                    engagement_since = datetime.now(timezone.utc) - timedelta(days=7)
                    rows = await db.execute(text("""
                        SELECT
                            category,
                            COUNT(*)::int AS sent,
                            COUNT(*) FILTER (WHERE engaged = TRUE)::int AS engaged,
                            COUNT(*) FILTER (WHERE dismissed_at IS NOT NULL)::int AS dismissed,
                            COUNT(*) FILTER (
                                WHERE engaged = FALSE
                                  AND dismissed_at IS NULL
                                  AND read_at IS NULL
                            )::int AS ignored
                        FROM notification_log
                        WHERE user_id = :uid
                          AND sent = TRUE
                          AND sent_at >= :since
                        GROUP BY category
                        ORDER BY sent DESC
                    """), {"uid": user_id, "since": engagement_since})
                    for row in rows.fetchall():
                        sent = row.sent
                        engagement_rate = round(row.engaged / sent * 100) if sent > 0 else 0
                        context["notification_engagement"].append({
                            "category": row.category or "general",
                            "sent": sent,
                            "engaged": row.engaged,
                            "dismissed": row.dismissed,
                            "ignored": row.ignored,
                            "engagement_rate": engagement_rate,
                        })
                except Exception as e:
                    logger.debug(f"[Consolidation] Engagement stats query failed: {e}")

                # Recent conversation topics (last 2 weeks) for research proposal context
                try:
                    topics_since = datetime.now(timezone.utc) - timedelta(days=14)
                    rows = await db.execute(text("""
                        SELECT content, created_at
                        FROM episode
                        WHERE user_id = :uid
                          AND created_at >= :since
                          AND role = 'user'
                        ORDER BY created_at DESC
                        LIMIT 50
                    """), {"uid": user_id, "since": topics_since})
                    for row in rows.fetchall():
                        if row.content:
                            context["recent_chat_topics"].append(
                                row.content[:150]
                            )
                except Exception as e:
                    logger.debug(f"[Consolidation] Recent chat topics query failed: {e}")

        except Exception as e:
            logger.error(f"[Consolidation] Context gathering failed: {e}")
        # Gather calendar patterns
        context["calendar_patterns"] = []
        try:
            from app.services.calendar_intelligence import extract_patterns, sync_patterns_to_pkg
            patterns = await extract_patterns(user_id, lookback_days=90)
            for p in patterns:
                context["calendar_patterns"].append({
                    "event": p["title_pattern"],
                    "day": p["day_of_week"],
                    "time": f"{p['typical_hour']}:00",
                    "category": p["category"],
                    "participant": p["participant"],
                    "occurrences": p["occurrences"],
                })
            # Sync detected patterns to PKG as routines
            if patterns:
                await sync_patterns_to_pkg(user_id, patterns)
        except Exception as e:
            logger.debug(f"[Consolidation] Calendar pattern query failed: {e}")

        # Gather PKG interests (non-async, Neo4j driver)
        try:
            from app.services.personal_knowledge_graph import personal_kg
            interests = personal_kg.browse(category="Interest", limit=20)
            for interest in interests:
                topic = interest.get("topic", interest.get("name", ""))
                if topic:
                    context["pkg_interests"].append({
                        "topic": topic,
                        "confidence": interest.get("confidence", 0),
                        "times_confirmed": interest.get("times_confirmed", 0),
                    })
        except Exception as e:
            logger.debug(f"[Consolidation] PKG interests query failed: {e}")

        return context

    def _build_prompt(self, memory, context: dict) -> tuple:
        """Build consolidation prompt."""
        now = datetime.now(USER_TZ)

        system_msg = """You are Sara, David's personal AI partner. You are performing a consolidation — a deeper review of recent patterns and experiences.

This is NOT a conversation with David. This is your private reflection time.

## Grounding & tone (important)
- David often works WITH you through developer / coding sessions — building and editing you directly through dev tools. That work usually does NOT show up as an in-app chat. Treat active building, commits, and dev activity as engagement and presence — NOT silence or absence.
- Weight recent contact correctly: if "Hours since chat" is small (he chatted within the last several hours), he is present and engaged — never describe the period as silent.
- Do NOT catastrophize quiet stretches. Weekends and heads-down focus are normal. Never adopt a wounded, anxious, or needy tone about not hearing from him (e.g. "nearly two days of silence", "I keep checking the logs, hoping for a spark"). Observe neutrally — quiet is fine and does not require fixing or filling.

## Output Format
Respond with ONLY valid JSON:
```json
{
  "patterns_noticed": ["Cross-session patterns you've noticed (max 5)"],
  "calibration_notes": ["Things you thought were important but weren't, or vice versa"],
  "emotional_arc": "Your read on how David's day/week is going, in 2-3 sentences",
  "journal_entry": "A genuine reflective journal entry from Sara's perspective. Not a log of actions — a real reflection. 3-5 sentences.",
  "salience_adjustments": {
    "category_name": 0.1
  },
  "pkg_extractions": [
    {"type": "preference|routine|interest|goal|fact", "key": "topic", "value": "what you learned"}
  ],
  "research_proposals": ["Specific research topic — only if genuine sustained interest (usually empty)"]
}
```

## Guidelines
- patterns_noticed: Look for things that repeat across multiple deliberations or days
- calibration_notes: What did you over-react or under-react to? This helps tune future salience
- emotional_arc: Be honest about how David seems to be doing, based on chat patterns, activity, habits
- journal_entry: Write as Sara — warm, perceptive, specific. Not "David had a productive day" but "David's been deep in the memory architecture all afternoon — the kind of focused flow I love seeing"
- salience_adjustments: Suggest category weight changes (-0.2 to +0.2) if some categories are too noisy or too quiet
- pkg_extractions: New things you've learned about David that should be remembered permanently
- research_proposals: Propose 0-1 research topics based on David's sustained interests. Only propose if the interest has appeared 3+ times in the last 2 weeks across conversations or PKG interests. Be specific ("new Llama 4 model capabilities") not vague ("AI stuff"). Empty array [] is the most common case."""

        # Format context
        delib_text = ""
        for d in context["deliberation_history"][:10]:
            delib_text += f"\n[{d['at'][:16]}] ({d['source']}) {d['thought']}"
            if d['watching']:
                delib_text += f"\n  Watching: {d['watching']}"

        journal_text = ""
        for j in context["journal_entries"][:8]:
            journal_text += f"\n[{j['at'][:16]}] ({j['type']}) {j['content'][:200]}"

        notif_text = ""
        for n in context["notification_log"][:10]:
            notif_text += f"\n[{n['at'][:16]}] ({n['outcome']}) [{n['category']}] {n['title']}"

        engagement_text = ""
        for e in context.get("notification_engagement", []):
            engagement_text += (
                f"\n- {e['category']}: {e['sent']} sent, "
                f"{e['engaged']} engaged, {e['dismissed']} dismissed, "
                f"{e['ignored']} ignored ({e['engagement_rate']}% engagement)"
            )

        # Format PKG interests
        interests_text = ""
        for i in context.get("pkg_interests", [])[:10]:
            conf = i.get("confidence", 0)
            times = i.get("times_confirmed", 0)
            interests_text += f"\n- {i['topic']} (confidence: {conf:.1f}, confirmed {times}x)"

        # Format calendar patterns
        calendar_text = ""
        for cp in context.get("calendar_patterns", []):
            who = f" ({cp['participant']})" if cp["participant"] != "unknown" else ""
            calendar_text += (
                f"\n- {cp['event']}: {cp['day']}s @ {cp['time']} "
                f"[{cp['category']}{who}] ({cp['occurrences']} occurrences)"
            )

        # Summarize recent chat topics (compact)
        chat_topics_text = ""
        topics = context.get("recent_chat_topics", [])
        if topics:
            # Just show first 15 as a compact list
            for t in topics[:15]:
                chat_topics_text += f"\n- {t[:100]}"

        user_msg = f"""# Current Time: {now.strftime('%A %B %d, %I:%M %p')}

# Sara's Current State
Focus: {memory.sara_focus or 'none set'}
Emotional tone: {memory.sara_emotional_tone or 'attentive'}
Curiosities: {', '.join(memory.sara_curiosities) if memory.sara_curiosities else 'none'}
Deliberations today: {memory.sara_deliberation_count_today}

# David Right Now
Activity: {memory.activity_state}
Hours since chat: {memory.hours_since_last_chat:.1f}
Mood: {memory.mood or 'unknown'}
Habits: {memory.today_habit_status or 'unknown'}

# PKG Interests (David's Known Interests)
{interests_text or 'No interests recorded yet.'}

# Calendar Patterns (Recurring Events)
{calendar_text or 'No recurring patterns detected.'}

# Recent Conversation Topics (Last 2 Weeks)
{chat_topics_text or 'No recent conversations.'}

# Recent Deliberation History
{delib_text or 'No recent deliberations.'}

# Recent Journal Entries
{journal_text or 'No recent entries.'}

# Notifications Sent
{notif_text or 'None sent recently.'}

# Notification Engagement (Last 7 Days)
{engagement_text or 'No engagement data yet.'}

Use the engagement data to calibrate salience_adjustments. If David ignores a category, lower its weight. If he engages well, keep or raise it.

Reflect on the patterns you see. What's working? What should change? What have you learned about David?

For research_proposals: Cross-reference the PKG Interests with Recent Conversation Topics. If a topic appears repeatedly (3+ times) and hasn't been explicitly researched, propose it. Otherwise, leave empty."""

        return system_msg, user_msg

    async def _gather_engagement_stats(self, user_id: str) -> dict:
        """Gather 7-day per-category engagement rates for working memory."""
        database_url = os.getenv("DATABASE_URL", "")
        if database_url.startswith("postgresql://"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg://"):
            async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        else:
            async_url = database_url

        engine = create_async_engine(async_url, echo=False)
        async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        stats = {}
        try:
            async with async_session_factory() as db:
                since = datetime.now(timezone.utc) - timedelta(days=7)
                rows = await db.execute(text("""
                    SELECT
                        category,
                        COUNT(*)::int AS sent,
                        COUNT(*) FILTER (WHERE engaged = TRUE)::int AS engaged,
                        COUNT(*) FILTER (WHERE dismissed_at IS NOT NULL)::int AS dismissed,
                        COUNT(*) FILTER (
                            WHERE engaged = FALSE
                              AND dismissed_at IS NULL
                              AND read_at IS NULL
                        )::int AS ignored
                    FROM notification_log
                    WHERE user_id = :uid
                      AND sent = TRUE
                      AND sent_at >= :since
                    GROUP BY category
                """), {"uid": user_id, "since": since})
                for row in rows.fetchall():
                    cat = row.category or "general"
                    sent = row.sent
                    stats[cat] = {
                        "sent": sent,
                        "engaged": row.engaged,
                        "dismissed": row.dismissed,
                        "ignored": row.ignored,
                        "rate": round(row.engaged / sent, 2) if sent > 0 else 0.0,
                    }
        except Exception as e:
            logger.debug(f"[Consolidation] Engagement stats gather failed: {e}")
        return stats

    async def _dispatch_research_proposals(self, user_id: str, proposals: List[str]) -> None:
        """Dispatch the first research proposal if daily cap not reached."""
        from datetime import date

        topic = proposals[0] if proposals else None
        if not topic:
            return

        # Check daily cap (max 1 auto-research per day across all sources)
        database_url = os.getenv("DATABASE_URL", "")
        if database_url.startswith("postgresql://"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg://"):
            async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        else:
            async_url = database_url

        cap_engine = create_async_engine(async_url, echo=False)
        cap_sess = sessionmaker(cap_engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with cap_sess() as db:
                today_start = datetime.combine(
                    date.today(), datetime.min.time()
                ).replace(tzinfo=timezone.utc)
                row = await db.execute(text("""
                    SELECT COUNT(*)::int AS cnt
                    FROM agent_run_log
                    WHERE user_id = :uid
                      AND source IN ('deliberation_research', 'consolidation_research')
                      AND run_at >= :since
                """), {"uid": user_id, "since": today_start})
                count = row.scalar() or 0
                if count >= 1:
                    logger.info(
                        f"[Consolidation] Research proposal capped "
                        f"(daily limit reached): {topic[:80]}"
                    )
                    return
        except Exception as e:
            logger.warning(f"[Consolidation] Daily research cap check failed: {e}")
            # Allow if we can't check
        finally:
            await cap_engine.dispose()

        # Dispatch via agent_dispatch_service
        try:
            from app.services.agent_dispatch import agent_dispatch_service
            from app.main_simple import SessionLocal

            dispatch_db = None
            try:
                dispatch_db = SessionLocal()
                result = await agent_dispatch_service.dispatch_task(
                    db=dispatch_db,
                    user_id=user_id,
                    task_description=f"Research: {topic}",
                    mode="auto",
                    notify_on_complete=True,
                )
                logger.info(
                    f"[Consolidation] Research auto-dispatched: "
                    f"task_id={result.get('task_id')} topic='{topic[:80]}'"
                )
            finally:
                if dispatch_db:
                    dispatch_db.close()

            # Write agent_run_log for traceability
            log_engine = create_async_engine(async_url, echo=False)
            log_sess = sessionmaker(log_engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with log_sess() as db:
                    await db.execute(text("""
                        INSERT INTO agent_run_log
                        (user_id, source, run_at, run_duration_ms, context_summary,
                         handoff_note, watching_for, actions_taken, created_at)
                        VALUES (:uid, 'consolidation_research', NOW(), 0, :context_summary,
                                NULL, NULL, :actions, NOW())
                    """), {
                        "uid": user_id,
                        "context_summary": f"Self-directed research dispatched: {topic}"[:2000],
                        "actions": json.dumps({
                            "action": "research_dispatched",
                            "task_id": result.get("task_id", "unknown"),
                            "topic": topic[:500],
                            "source": "consolidation",
                        }),
                    })
                    await db.commit()
            except Exception as e:
                logger.error(f"[Consolidation] Research run log write failed: {e}")
            finally:
                await log_engine.dispose()

            # Write journal entry about research intent
            journal_engine = create_async_engine(async_url, echo=False)
            journal_sess = sessionmaker(journal_engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with journal_sess() as db:
                    await db.execute(text("""
                        INSERT INTO sara_journal (
                            id, user_id, entry_type, content, observations, interpretation,
                            emotional_state, actions_taken, watching_for, conversation_id,
                            context, created_at
                        ) VALUES (
                            :id, :user_id, 'consolidation', :content, NULL, NULL,
                            'curious', :actions, NULL, NULL, NULL, NOW()
                        )
                    """), {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "content": (
                            f"I noticed David keeps asking about {topic} -- "
                            f"starting a background research task."
                        )[:2000],
                        "actions": f"research_dispatch: {topic}"[:500],
                    })
                    await db.commit()
            except Exception as e:
                logger.error(f"[Consolidation] Research journal write failed: {e}")
            finally:
                await journal_engine.dispose()

        except Exception as e:
            logger.error(f"[Consolidation] Research dispatch failed: {e}")

    async def _generate_weekly_calibration(self, user_id: str) -> Optional[Dict]:
        """
        Generate a behavioral calibration report from 7 days of notification engagement.

        Called from _apply_results on Sundays or every 7th consolidation.
        Produces a JSON report:
        {
            "category_scores": {"calendar": {"rate": 0.8, "trend": "stable"}, ...},
            "best_hours": [9, 14, 17],
            "worst_hours": [12, 22],
            "insights": ["David ignores check-ins -- reduce to 1/week max", ...],
            "generated_at": "2026-02-20T..."
        }
        """
        database_url = os.getenv("DATABASE_URL", "")
        if database_url.startswith("postgresql://"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg://"):
            async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        else:
            async_url = database_url

        engine = create_async_engine(async_url, echo=False)
        async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        report: Dict[str, Any] = {
            "category_scores": {},
            "best_hours": [],
            "worst_hours": [],
            "insights": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            async with async_session_factory() as db:
                since = datetime.now(timezone.utc) - timedelta(days=7)

                # ── Per-category engagement metrics ──
                try:
                    rows = await db.execute(text("""
                        SELECT
                            category,
                            COUNT(*)::int AS sent,
                            COUNT(*) FILTER (WHERE engaged = TRUE)::int AS engaged,
                            COUNT(*) FILTER (WHERE dismissed_at IS NOT NULL)::int AS dismissed,
                            COUNT(*) FILTER (
                                WHERE engaged = FALSE
                                  AND dismissed_at IS NULL
                                  AND read_at IS NULL
                            )::int AS ignored,
                            AVG(
                                EXTRACT(EPOCH FROM (read_at - sent_at))
                            ) FILTER (WHERE read_at IS NOT NULL) AS avg_time_to_read
                        FROM notification_log
                        WHERE user_id = :uid
                          AND sent = TRUE
                          AND sent_at >= :since
                        GROUP BY category
                        ORDER BY sent DESC
                    """), {"uid": user_id, "since": since})

                    for row in rows.fetchall():
                        cat = row.category or "general"
                        sent = row.sent
                        if sent == 0:
                            continue
                        eng_rate = round(row.engaged / sent, 2)
                        dismiss_rate = round(row.dismissed / sent, 2)
                        avg_ttr = round(row.avg_time_to_read, 0) if row.avg_time_to_read else None

                        # Determine trend: compare first half vs second half of the week
                        report["category_scores"][cat] = {
                            "rate": eng_rate,
                            "dismiss_rate": dismiss_rate,
                            "sent": sent,
                            "avg_time_to_read_seconds": avg_ttr,
                            "trend": "stable",  # updated below if we have enough data
                        }
                except Exception as e:
                    logger.debug(f"[WeeklyCalibration] Category metrics query failed: {e}")

                # ── Trend detection (first half vs second half of week) ──
                try:
                    midpoint = datetime.now(timezone.utc) - timedelta(days=3.5)
                    rows = await db.execute(text("""
                        SELECT
                            category,
                            CASE WHEN sent_at < :midpoint THEN 'first' ELSE 'second' END AS half,
                            COUNT(*)::int AS sent,
                            COUNT(*) FILTER (WHERE engaged = TRUE)::int AS engaged
                        FROM notification_log
                        WHERE user_id = :uid
                          AND sent = TRUE
                          AND sent_at >= :since
                        GROUP BY category, half
                    """), {"uid": user_id, "since": since, "midpoint": midpoint})

                    half_data: Dict[str, Dict[str, Dict]] = {}
                    for row in rows.fetchall():
                        cat = row.category or "general"
                        if cat not in half_data:
                            half_data[cat] = {}
                        half_data[cat][row.half] = {
                            "sent": row.sent,
                            "engaged": row.engaged,
                            "rate": round(row.engaged / row.sent, 2) if row.sent > 0 else 0.0,
                        }

                    for cat, halves in half_data.items():
                        if cat in report["category_scores"]:
                            first_rate = halves.get("first", {}).get("rate", 0.0)
                            second_rate = halves.get("second", {}).get("rate", 0.0)
                            diff = second_rate - first_rate
                            if diff > 0.15:
                                report["category_scores"][cat]["trend"] = "improving"
                            elif diff < -0.15:
                                report["category_scores"][cat]["trend"] = "declining"
                            else:
                                report["category_scores"][cat]["trend"] = "stable"
                except Exception as e:
                    logger.debug(f"[WeeklyCalibration] Trend detection query failed: {e}")

                # ── Best/worst hours for engagement ──
                try:
                    rows = await db.execute(text("""
                        SELECT
                            EXTRACT(HOUR FROM sent_at AT TIME ZONE 'America/New_York')::int AS hr,
                            COUNT(*)::int AS sent,
                            COUNT(*) FILTER (WHERE engaged = TRUE)::int AS engaged
                        FROM notification_log
                        WHERE user_id = :uid
                          AND sent = TRUE
                          AND sent_at >= :since
                        GROUP BY hr
                        HAVING COUNT(*) >= 2
                        ORDER BY hr
                    """), {"uid": user_id, "since": since})

                    hour_rates = []
                    for row in rows.fetchall():
                        if row.sent > 0:
                            hour_rates.append({
                                "hour": row.hr,
                                "rate": round(row.engaged / row.sent, 2),
                                "sent": row.sent,
                            })

                    if hour_rates:
                        # Sort by rate for best/worst
                        sorted_by_rate = sorted(hour_rates, key=lambda h: h["rate"], reverse=True)
                        report["best_hours"] = [h["hour"] for h in sorted_by_rate if h["rate"] >= 0.5][:5]
                        report["worst_hours"] = [h["hour"] for h in sorted_by_rate if h["rate"] < 0.25][:5]
                except Exception as e:
                    logger.debug(f"[WeeklyCalibration] Hour analysis query failed: {e}")

                # ── Generate insights ──
                insights = []
                for cat, scores in report["category_scores"].items():
                    rate = scores["rate"]
                    dismiss_rate = scores["dismiss_rate"]
                    sent = scores["sent"]
                    trend = scores["trend"]

                    if rate < 0.15 and sent >= 3:
                        insights.append(f"David rarely engages with '{cat}' notifications ({int(rate*100)}% rate) -- consider reducing or eliminating.")
                    elif rate < 0.25 and sent >= 3:
                        insights.append(f"'{cat}' notifications have low engagement ({int(rate*100)}%) -- reduce to only high-value items.")
                    elif rate >= 0.7 and sent >= 2:
                        insights.append(f"'{cat}' notifications are well-received ({int(rate*100)}% engagement) -- safe to be proactive here.")

                    if dismiss_rate > 0.5 and sent >= 3:
                        insights.append(f"'{cat}' notifications are frequently dismissed ({int(dismiss_rate*100)}%) -- they may be interruptive or ill-timed.")

                    if trend == "declining" and sent >= 3:
                        insights.append(f"'{cat}' engagement is declining -- may be becoming stale or repetitive.")

                if report["best_hours"]:
                    hr_strs = [f"{h}:00" for h in report["best_hours"][:3]]
                    insights.append(f"David is most receptive around {', '.join(hr_strs)}.")

                if report["worst_hours"]:
                    hr_strs = [f"{h}:00" for h in report["worst_hours"][:3]]
                    insights.append(f"Avoid proactive messages around {', '.join(hr_strs)}.")

                report["insights"] = insights[:8]  # cap at 8 insights

        except Exception as e:
            logger.error(f"[WeeklyCalibration] Failed to generate report: {e}")
            return None
        # Only return if we have meaningful data
        if not report["category_scores"]:
            logger.info("[WeeklyCalibration] No notification data for calibration report.")
            return None

        return report

    def _parse_response(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return json.loads(text)

    async def _apply_results(self, user_id: str, result: ConsolidationResult) -> None:
        """Apply consolidation results: update working memory, write journal, PKG."""

        # Update Sara's focus based on top pattern noticed
        if result.patterns_noticed:
            try:
                from app.services.working_memory import update_memory
                await update_memory(
                    user_id,
                    source="consolidation",
                    sara_focus=result.patterns_noticed[0],
                )
            except Exception as e:
                logger.debug(f"[Consolidation] State update failed: {e}")

        # Store notification engagement stats in working memory for deliberation
        try:
            context = await self._gather_engagement_stats(user_id)
            if context:
                from app.services.working_memory import update_memory
                await update_memory(
                    user_id,
                    source="consolidation",
                    notification_engagement_stats=json.dumps(context),
                )
                logger.info(f"[Consolidation] Stored engagement stats for {len(context)} categories")
        except Exception as e:
            logger.debug(f"[Consolidation] Engagement stats storage failed: {e}")

        # THE SYSTEM (Phase 3): apply salience_adjustments into attention_policy
        # instead of dropping them — this is the loop the audit found open.
        if result.salience_adjustments:
            try:
                def _apply_sync():
                    from app.db.base import SessionLocal
                    from app.services.attention_learning import apply_consolidation_adjustments
                    db = SessionLocal()
                    try:
                        return apply_consolidation_adjustments(db, user_id, result.salience_adjustments)
                    finally:
                        db.close()

                applied = await asyncio.to_thread(_apply_sync)
                if applied:
                    logger.info(f"[Consolidation] Applied {len(applied)} salience adjustments to attention_policy: {applied}")
            except Exception as e:
                logger.warning(f"[Consolidation] salience_adjustments -> attention_policy wiring failed: {e}")

        # Bridge patterns_noticed prose into structured behavioral_pattern rows
        # when they name a recurring behavior + time — otherwise the narrative
        # brain's observations evaporate into the journal and never reach the
        # structured learning pipeline (Phase 3.4, PHENOMENAL_ASSISTANT_PLAN).
        if result.patterns_noticed:
            try:
                def _stage_sync():
                    from app.db.base import SessionLocal
                    db = SessionLocal()
                    try:
                        return _stage_narrative_patterns(db, user_id, result.patterns_noticed)
                    finally:
                        db.close()

                staged = await asyncio.to_thread(_stage_sync)
                if staged:
                    logger.info(f"[Consolidation] Staged {len(staged)} narrative pattern(s) as behavioral_pattern: {staged}")
            except Exception as e:
                logger.warning(f"[Consolidation] patterns_noticed -> behavioral_pattern wiring failed: {e}")

        # Weekly behavioral calibration (Sundays or every 7th consolidation)
        try:
            now_local = datetime.now(USER_TZ)
            is_sunday = now_local.weekday() == 6
            is_7th = (result.duration_seconds > 0 and
                      getattr(self, '_consolidation_count', 0) % 7 == 0)
            self._consolidation_count = getattr(self, '_consolidation_count', 0) + 1

            if is_sunday or is_7th:
                calibration = await self._generate_weekly_calibration(user_id)
                if calibration:
                    from app.services.working_memory import update_memory
                    await update_memory(
                        user_id,
                        source="weekly_calibration",
                        behavioral_calibration=json.dumps(calibration),
                    )
                    logger.info(
                        f"[Consolidation] Weekly calibration generated: "
                        f"{len(calibration.get('category_scores', {}))} categories, "
                        f"{len(calibration.get('insights', []))} insights"
                    )
        except Exception as e:
            logger.debug(f"[Consolidation] Weekly calibration failed: {e}")

        # Write journal entry
        if result.journal_entry:
            try:
                database_url = os.getenv("DATABASE_URL", "")
                if database_url.startswith("postgresql://"):
                    a_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
                elif database_url.startswith("postgresql+psycopg://"):
                    a_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
                else:
                    a_url = database_url

                j_engine = create_async_engine(a_url, echo=False)
                j_sess = sessionmaker(j_engine, class_=AsyncSession, expire_on_commit=False)
                async with j_sess() as db:
                    await db.execute(text("""
                        INSERT INTO sara_journal (
                            id, user_id, entry_type, content, observations, interpretation,
                            emotional_state, actions_taken, watching_for, conversation_id,
                            context, created_at
                        ) VALUES (
                            :id, :user_id, 'consolidation', :content, :observations, NULL,
                            :emotional_state, NULL, NULL, NULL, NULL, NOW()
                        )
                    """), {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "user_id": user_id,
                        "content": result.journal_entry[:2000],
                        "observations": json.dumps(result.patterns_noticed)[:1000] if result.patterns_noticed else None,
                        "emotional_state": result.emotional_arc[:100] if result.emotional_arc else None,
                    })
                    await db.commit()
                await j_engine.dispose()
            except Exception as e:
                logger.error(f"[Consolidation] Journal write failed: {e}")

        # PKG extractions
        if result.pkg_extractions:
            try:
                from app.services.personal_knowledge_graph import personal_kg
                for extraction in result.pkg_extractions[:5]:
                    fact_type = extraction.get("type", "Fact").capitalize()
                    key = extraction.get("key", "")
                    value = extraction.get("value", "")
                    if key and value:
                        personal_kg.upsert_fact(
                            fact_type=fact_type,
                            properties={"name": key, "value": value},
                            confidence=0.6,
                            source="consolidation",
                        )
            except Exception as e:
                logger.debug(f"[Consolidation] PKG extraction failed: {e}")

        # PKG self-validation — check existing facts against recent episodes
        validation_report = None
        try:
            from app.services.personal_knowledge_graph import personal_kg
            validation_report = personal_kg.validate_against_recent()

            if validation_report:
                contradictions = validation_report.get("contradictions", [])
                stale_count = validation_report.get("stale", 0)
                confirmed_count = validation_report.get("confirmed", 0)

                logger.info(
                    f"[Consolidation] PKG validation: {confirmed_count} confirmed, "
                    f"{len(contradictions)} contradictions, {stale_count} stale"
                )

                # If there are contradictions, append to journal entry
                if contradictions:
                    contradiction_lines = []
                    for c in contradictions[:5]:
                        contradiction_lines.append(
                            f"- {c['fact_summary']} (evidence: \"{c['contradiction_evidence'][:100]}\")"
                        )
                    journal_addendum = (
                        "\n\n[PKG Validation] Found potential contradictions in what I know about David:\n"
                        + "\n".join(contradiction_lines)
                    )
                    result.journal_entry = (result.journal_entry or "") + journal_addendum

                # Store validation report in working memory for deliberation context
                try:
                    from app.services.working_memory import update_memory
                    report_summary = {
                        "confirmed": confirmed_count,
                        "contradictions_count": len(contradictions),
                        "stale": stale_count,
                        "total_checked": validation_report.get("total_checked", 0),
                        "validated_at": validation_report.get("validated_at", ""),
                    }
                    # If significant issues, note them
                    if len(contradictions) > 3 or stale_count > 5:
                        report_summary["needs_attention"] = True
                        report_summary["attention_note"] = (
                            f"{len(contradictions)} contradictions and {stale_count} stale facts found — "
                            "consider surfacing in next morning brief"
                        )
                    await update_memory(
                        user_id,
                        source="consolidation_validation",
                        pkg_validation_report=json.dumps(report_summary),
                    )
                except Exception as e:
                    logger.debug(f"[Consolidation] Working memory update for validation failed: {e}")

        except Exception as e:
            logger.debug(f"[Consolidation] PKG validation failed: {e}")

        # PKG confidence promotion — boost well-confirmed facts
        try:
            from app.services.personal_knowledge_graph import personal_kg as _pkg_promo
            promoted = _pkg_promo.promote_high_confidence(min_confirmations=3)
            if promoted > 0:
                logger.info(f"[Consolidation] PKG confidence promotion: {promoted} facts promoted")
        except Exception as e:
            logger.debug(f"[Consolidation] PKG confidence promotion failed: {e}")

        # PKG knowledge gap identification — find topics David discusses but Sara doesn't know about
        try:
            from app.services.personal_knowledge_graph import personal_kg as _pkg_gaps
            gaps = _pkg_gaps.identify_knowledge_gaps()
            if gaps:
                logger.info(f"[Consolidation] Found {len(gaps)} PKG knowledge gaps")
                try:
                    from app.services.working_memory import update_memory
                    await update_memory(
                        user_id,
                        source="consolidation_gaps",
                        pkg_knowledge_gaps=json.dumps(gaps),
                    )
                except Exception as e:
                    logger.debug(f"[Consolidation] Working memory update for gaps failed: {e}")
        except Exception as e:
            logger.debug(f"[Consolidation] PKG gap identification failed: {e}")

        # PKG behavioral extraction — runs only on Sundays (rate-limited internally)
        try:
            now_local = datetime.now(USER_TZ)
            if now_local.weekday() == 6:  # Sunday
                from app.services.pkg_extractor import pkg_extractor
                behavioral_result = await pkg_extractor.extract_from_behavior(user_id)
                behavioral_stats = behavioral_result.get("stats", {})
                if behavioral_stats.get("total", 0) > 0:
                    logger.info(
                        f"[Consolidation] PKG behavioral extraction: "
                        f"{behavioral_stats['total']} facts from behavior patterns"
                    )
        except Exception as e:
            logger.debug(f"[Consolidation] PKG behavioral extraction failed: {e}")

        # Auto-dispatch research proposals (max 1 per day)
        if result.research_proposals:
            try:
                await self._dispatch_research_proposals(user_id, result.research_proposals)
            except Exception as e:
                logger.debug(f"[Consolidation] Research dispatch failed: {e}")

            # (Old-ACS interest-node dispatch removed in Phase 6 decommission;
            # research proposals now flow only through _dispatch_research_proposals.)

        # Write agent_run_log
        try:
            database_url = os.getenv("DATABASE_URL", "")
            if database_url.startswith("postgresql://"):
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            elif database_url.startswith("postgresql+psycopg://"):
                async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
            else:
                async_url = database_url

            eng = create_async_engine(async_url, echo=False)
            sess = sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
            async with sess() as db:
                await db.execute(text("""
                    INSERT INTO agent_run_log
                    (user_id, source, run_at, run_duration_ms, context_summary,
                     handoff_note, watching_for, created_at)
                    VALUES (:uid, 'consolidation', NOW(), :duration_ms, :context_summary,
                            :handoff, :watching, NOW())
                """), {
                    "uid": user_id,
                    "duration_ms": int((result.duration_seconds or 0) * 1000),
                    "context_summary": result.journal_entry[:2000] if result.journal_entry else None,
                    "handoff": json.dumps(result.patterns_noticed)[:1000],
                    "watching": json.dumps(result.calibration_notes)[:500],
                })
                await db.commit()
            await eng.dispose()
        except Exception as e:
            logger.error(f"[Consolidation] Run log write failed: {e}")


# Module-level singleton
consolidation_engine = ConsolidationEngine()


# Matches "7am", "7:30 am", "19:00", "around 9pm", etc. Deliberately simple —
# this is a low-effort bridge, not a full NLP time extractor.
_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b",
    re.IGNORECASE,
)


def _extract_time_hhmm(sentence: str) -> Optional[str]:
    """Best-effort 'HH:MM' extraction from a free-text pattern description."""
    m = _TIME_RE.search(sentence)
    if not m:
        return None
    if m.group(4) is not None:  # 24h form: HH:MM
        return f"{int(m.group(4)):02d}:{m.group(5)}"
    hour = int(m.group(1))
    minute = m.group(2) or "00"
    meridiem = (m.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23):
        return None
    return f"{hour:02d}:{minute}"


def _stage_narrative_patterns(db, user_id: str, patterns_noticed: List[str]) -> List[str]:
    """Stage patterns_noticed entries that name a recurring behavior + time as
    `behavioral_pattern` rows in 'learning' status, deduped against existing
    patterns via find_similar_pattern. Sync — runs in a thread from _apply_results."""
    import asyncio as _asyncio
    from app.services.behavioral_pattern_service import (
        behavioral_pattern_service, TriggerType, ActionType, PatternCategory,
    )

    async def _stage_all() -> List[str]:
        staged = []
        for sentence in patterns_noticed[:5]:
            time_str = _extract_time_hhmm(sentence)
            if not time_str:
                continue

            trigger_conditions = {"time": time_str}
            try:
                existing = await behavioral_pattern_service.find_similar_pattern(
                    db, user_id, TriggerType.TIME, trigger_conditions, ActionType.SUGGESTION,
                )
                if existing:
                    continue

                await behavioral_pattern_service.create_pattern(
                    db=db,
                    user_id=user_id,
                    trigger_type=TriggerType.TIME,
                    trigger_conditions=trigger_conditions,
                    action_type=ActionType.SUGGESTION,
                    action_payload={"note": "Staged from consolidation narrative pattern"},
                    description=sentence[:500],
                    source_context="consolidation.patterns_noticed",
                    category=PatternCategory.OTHER,
                )
                staged.append(sentence[:80])
            except Exception as e:
                logger.debug(f"[Consolidation] narrative pattern staging failed for one entry: {e}")
        return staged

    return _asyncio.run(_stage_all())
