"""
Deliberation Gate — validates and executes deliberation outputs.

After the deliberation engine produces proposals, this gate:
1. Validates notifications against HEARTBEAT.md hard bans
2. Delivers notifications via the existing pipeline (dedup, interruptibility)
3. Executes home actions via ha_control_service
4. Routes task proposals through autonomy tiers (auto-execute / propose / block)
5. Updates Sara's internal state in working memory
6. Consumes processed observations
7. Writes journal entry and agent_run_log
"""

import json
import logging
import re
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Optional
from app.core.timezone import now as local_now

from app.services.deliberation import DeliberationResult, NotificationProposal, HomeActionProposal, TaskProposal
from app.services.silent_failure_tracker import Tracker

logger = logging.getLogger(__name__)

# Single tracker per gate — reasons differentiate the 8 post-deliberation
# side-effect paths that used to fail to DEBUG-only logs.
_GATE_TRACKER = Tracker("deliberation_gate")

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Hard-banned notification topics (from HEARTBEAT.md)
# Comprehensive list — covers health, fitness, biometrics, nutrition, and body-state topics.
_BANNED_PHRASES = [
    # Nutrition / eating (original)
    "blood sugar", "nutrition", "hungry", "meal timing", "eating",
    "haven't eaten", "should eat", "food intake", "calorie",
    "caloric", "macros", "protein intake", "carb intake",
    # Body-state / subjective (original)
    "alertness", "sleep debt", "fatigue", "stress level",
    "you seem tired", "energy level",
    # Heart / cardiovascular
    "hrv", "heart rate variability", "heart rate", "resting heart rate",
    "resting hr", "elevated heart rate", "pulse rate",
    "blood pressure", "systolic", "diastolic",
    # Sleep
    "sleep score", "sleep quality", "sleep duration", "sleep cycle",
    "sleep stage", "rem sleep", "deep sleep", "light sleep",
    "sleep efficiency", "time in bed",
    # Recovery / readiness
    "recovery score", "recovery status", "readiness score",
    "readiness", "body battery", "strain score",
    # Workout / exercise
    "workout", "exercise", "training load", "training session",
    "gym session", "rep count", "set count", "training volume",
    "exercise reminder", "time to work out", "haven't exercised",
    "skip leg day",
    # Body composition / weight
    "body weight", "weight loss", "weight gain", "bmi",
    "body fat", "lean mass", "body composition", "weigh yourself",
    "scale reading",
    # Hydration
    "hydration", "water intake", "dehydration", "drink more water",
    "fluid intake",
    # Soreness / muscle
    "soreness", "muscle recovery", "doms", "muscle soreness",
    "delayed onset",
    # Steps / activity tracking
    "step count", "steps today", "active minutes", "move ring",
    "stand hours", "activity ring", "daily steps",
    "steps goal", "move goal",
    # Calories / energy expenditure
    "calories burned", "calorie burn", "energy expenditure",
    "active calories", "total calories",
    # Respiratory
    "vo2", "vo2 max", "vo2max", "oxygen saturation", "spo2",
    "respiratory rate", "breathing rate", "breath rate",
    # Temperature
    "body temperature", "skin temperature", "core temperature",
    "temp reading",
    # Wearable-specific metrics
    "whoop", "oura ring", "garmin score", "fitbit score",
    "apple watch health", "health ring",
]

# Hard-banned notification categories — any notification whose category matches is auto-rejected.
_BANNED_CATEGORIES = {"health", "fitness", "wellness"}

# Hard-banned home actions
_BANNED_ENTITIES = [
    "switch.heater", "switch.space_heater", "climate.heater",
]

# Autonomy tiers for task proposals
AUTO_EXECUTE_CATEGORIES = {"research", "pkg_update", "note_organization", "home_control", "maintenance"}
PROPOSE_FIRST_CATEGORIES = {"calendar_change", "user_facing"}
HARD_BLOCK_CATEGORIES = {"email_send", "purchase", "external_message"}


def _normalize_journal_text(content: str) -> str:
    text = (content or "").lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _journal_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_journal_text(a), _normalize_journal_text(b)).ratio()


_COMPLETION_ANNOUNCEMENT_RE = re.compile(
    r"\b(research|report|task|investigation|agents?|background (?:work|job))\b"
    r".{0,60}\b(is ready|ready for you|complete[d]?|finished|done|wrapped up)\b"
)


# ── Measured un-gag (THE SYSTEM, Phase 4) ──────────────────────────────────
# The blanket category/phrase ban above was a band-aid for Sara's fitness bias.
# Un-gag PER DOMAIN via tunable flags `system.ungag.<domain>` (default OFF), or a
# master `system.ungag.all`. When a domain is un-gagged, the learned attention
# policy + anomaly override govern instead of the hard ban. Cached 60s.
import time as _time

_UNGAG_DOMAIN = {"health": "health", "fitness": "health", "wellness": "health"}
_ungag_cache = {"at": 0.0, "flags": {}}


def _ungag_flags() -> dict:
    now = _time.time()
    if now - _ungag_cache["at"] < 60:
        return _ungag_cache["flags"]
    flags = {}
    try:
        from sqlalchemy import text as _text
        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            rows = db.execute(_text("SELECT key, value FROM tunable_setting WHERE key LIKE 'system.ungag.%'")).fetchall()
            for k, v in rows:
                dom = k.rsplit(".", 1)[-1]
                s = str(v).strip().strip('"').lower()
                flags[dom] = s in ("1", "true", "yes", "on")
        finally:
            db.close()
    except Exception:
        pass
    _ungag_cache["at"] = now
    _ungag_cache["flags"] = flags
    return flags


def _is_ungagged(category: Optional[str]) -> bool:
    flags = _ungag_flags()
    if flags.get("all"):
        return True
    dom = _UNGAG_DOMAIN.get((category or "").lower(), (category or "").lower())
    return bool(flags.get(dom, False))


def _is_banned_notification(proposal: NotificationProposal) -> Optional[str]:
    """Check if a notification proposal violates hard bans. Returns ban reason or None."""
    cat = proposal.category if hasattr(proposal, "category") else None
    ungagged = _is_ungagged(cat)
    # Category-level ban (skipped if this domain has been un-gagged)
    if cat and cat.lower() in _BANNED_CATEGORIES and not ungagged:
        return f"Hard ban: category '{cat}' is banned"
    text = f"{proposal.title} {proposal.message}".lower()
    if not ungagged:
        for phrase in _BANNED_PHRASES:
            if phrase in text:
                return f"Hard ban: contains '{phrase}'"
    # Deliberation must not announce background-work completions. The delivery
    # service already tells David exactly once at completion time; a completed
    # task lingering in deliberation context kept getting re-announced for days
    # with fresh phrasing that slipped past the content-hash dedup.
    if _COMPLETION_ANNOUNCEMENT_RE.search(text):
        return "Hard ban: completed-work announcements are owned by task_result_delivery"
    return None


def is_notification_banned(
    title: str,
    message: str,
    category: str = "general",
    custom_ban_phrases: Optional[list] = None,
) -> Optional[str]:
    """
    Public ban-check used by both deliberation_gate and unified_notification.

    Returns a ban reason string if the notification should be blocked, or None if allowed.
    """
    ungagged = _is_ungagged(category)
    # Category-level ban (skipped if this domain has been un-gagged)
    if category and category.lower() in _BANNED_CATEGORIES and not ungagged:
        return f"Banned category: {category}"
    # Phrase-level ban
    text = f"{title} {message}".lower()
    all_phrases = [] if ungagged else list(_BANNED_PHRASES)
    if custom_ban_phrases:
        all_phrases.extend(p.lower().strip() for p in custom_ban_phrases if p and p.strip())
    for phrase in all_phrases:
        if phrase in text:
            return f"Banned phrase: '{phrase}'"
    return None


def _is_banned_action(action: HomeActionProposal) -> Optional[str]:
    """Check if a home action violates hard bans. Returns ban reason or None."""
    for banned in _BANNED_ENTITIES:
        if banned in action.entity_id.lower():
            return f"Hard ban: entity '{action.entity_id}' is banned"
    return None


async def process_deliberation_result(
    result: DeliberationResult,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """
    Validate and execute all deliberation outputs.
    Returns summary dict for logging.
    """
    summary = {
        "notifications_sent": 0,
        "notifications_blocked": 0,
        "home_actions_executed": 0,
        "home_actions_blocked": 0,
        "tasks_dispatched": 0,
        "tasks_proposed": 0,
        "tasks_blocked": 0,
        "research_dispatched": 0,
        "research_capped": 0,
        "observations_consumed": 0,
        "state_updated": False,
        "journal_written": False,
    }

    # 1. Process notification proposals
    total_proposed = len(result.notification_proposals)
    capped_proposals = result.notification_proposals[:2]
    if total_proposed > 2:
        logger.info(
            f"[DeliberationGate] Notification cap: {total_proposed} proposed, "
            f"processing first 2"
        )
    for i, proposal in enumerate(capped_proposals):
        ban_reason = _is_banned_notification(proposal)
        if ban_reason:
            logger.info(
                f"[DeliberationGate] Notification [{i+1}/{len(capped_proposals)}] BLOCKED: "
                f"category={proposal.category}, title='{proposal.title[:60]}', "
                f"reason={ban_reason}"
            )
            summary["notifications_blocked"] += 1
            continue

        try:
            logger.info(
                f"[DeliberationGate] Notification [{i+1}/{len(capped_proposals)}] DELIVERING: "
                f"category={proposal.category}, priority={proposal.priority}, "
                f"title='{proposal.title[:60]}'"
            )
            await _deliver_notification(user_id, proposal)
            summary["notifications_sent"] += 1
        except Exception as e:
            _GATE_TRACKER.note(f"notify_delivery:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Notification delivery failed: {e}")

    # 2. Process home actions
    for action in result.home_actions[:3]:  # cap at 3
        ban_reason = _is_banned_action(action)
        if ban_reason:
            logger.info(f"[DeliberationGate] Home action blocked: {ban_reason}")
            summary["home_actions_blocked"] += 1
            continue

        try:
            await _execute_home_action(user_id, action)
            summary["home_actions_executed"] += 1
        except Exception as e:
            _GATE_TRACKER.note(f"home_action:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Home action failed: {e}")

    # 3. Process task proposals
    if result.task_proposals:
        await _process_task_proposals(user_id, result.task_proposals, summary)

    # 3b. Process research proposals
    if result.research_proposals:
        await _process_research_proposals(user_id, result.research_proposals, summary)

    # 4. Update Sara's internal state in working memory
    # Always bump deliberation timestamp and count (even on parse failure)
    # to prevent repeated LLM calls when the model keeps returning bad JSON.
    try:
        from app.services.working_memory import update_sara_state, increment_deliberation_count
        await update_sara_state(
            user_id,
            focus=result.state_update.get("focus") if result.state_update else None,
            emotional_tone=result.state_update.get("emotional_tone") if result.state_update else None,
            curiosities=result.state_update.get("curiosities") if result.state_update else None,
            deliberation_happened=True,
        )
        await increment_deliberation_count(user_id)
        summary["state_updated"] = bool(result.state_update)
    except Exception as e:
        _GATE_TRACKER.note(f"state_update:{type(e).__name__}")
        logger.error(f"[DeliberationGate] State update failed: {e}")

    # 5. Update handoff note and watching_for in working memory
    try:
        from app.services.working_memory import read_memory, update_memory
        fields = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        if result.handoff_note:
            # Only update handoff_set_at when the content actually changes
            current = await read_memory(user_id)
            old_handoff = getattr(current, 'last_heartbeat_handoff', '') or ''
            if result.handoff_note.strip() != old_handoff.strip():
                fields["last_heartbeat_handoff"] = result.handoff_note
                fields["last_handoff_set_at"] = now_iso
        if result.watching_for:
            fields["last_heartbeat_watching_for"] = result.watching_for
        fields["last_heartbeat_at"] = now_iso
        await update_memory(user_id, source="deliberation_gate", **fields)
    except Exception as e:
        _GATE_TRACKER.note(f"handoff:{type(e).__name__}")
        logger.error(f"[DeliberationGate] Handoff update failed: {e}")

    # 6. Consume processed observations
    if result.observations_consumed:
        try:
            from app.services.observation_log import consume_observations
            consumed = await consume_observations(user_id, result.observations_consumed)
            summary["observations_consumed"] = consumed
        except Exception as e:
            _GATE_TRACKER.note(f"obs_consume:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Observation consumption failed: {e}")

    # 7. Write journal entry
    if result.thought:
        try:
            await _write_journal(user_id, result)
            summary["journal_written"] = True
        except Exception as e:
            _GATE_TRACKER.note(f"journal:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Journal write failed: {e}")

    # 8. Write agent_run_log
    try:
        await _write_run_log(user_id, result, summary)
    except Exception as e:
        _GATE_TRACKER.note(f"run_log:{type(e).__name__}")
        logger.error(f"[DeliberationGate] Run log write failed: {e}")

    logger.info(f"[DeliberationGate] Result: {summary}")
    return summary


async def _process_task_proposals(
    user_id: str,
    proposals: list,
    summary: dict,
) -> None:
    """Validate and route task proposals through autonomy tiers."""
    for proposal in proposals[:2]:  # cap at 2 per deliberation
        if proposal.category in HARD_BLOCK_CATEGORIES:
            logger.info(f"[DeliberationGate] Task blocked (hard ban): {proposal.category} — {proposal.description[:80]}")
            summary["tasks_blocked"] += 1
            continue

        if proposal.category in AUTO_EXECUTE_CATEGORIES and proposal.confidence >= 0.6:
            # Research auto-dispatch is gated: it must respect the daily research
            # cap AND must not re-dispatch a topic already attempted recently.
            # Without this, a research task that can't succeed (the agent hangs
            # and auto-expires after 4h) gets re-proposed and re-dispatched every
            # deliberation cycle — looping forever on the same subject.
            if proposal.category == "research":
                skip_reason = await _research_should_skip(user_id, proposal)
                if skip_reason:
                    summary["tasks_skipped"] = summary.get("tasks_skipped", 0) + 1
                    logger.info(
                        f"[DeliberationGate] Research auto-dispatch skipped "
                        f"({skip_reason}): {proposal.description[:80]}"
                    )
                    continue
            # Auto-execute: dispatch directly, notify after completion
            try:
                await _dispatch_from_deliberation(user_id, proposal)
                summary["tasks_dispatched"] += 1
                logger.info(f"[DeliberationGate] Task auto-dispatched: {proposal.category} — {proposal.description[:80]}")
            except Exception as e:
                logger.error(f"[DeliberationGate] Task dispatch failed: {e}")
        else:
            # Propose to David via notification
            try:
                await _propose_task_to_david(user_id, proposal)
                summary["tasks_proposed"] += 1
                logger.info(f"[DeliberationGate] Task proposed to David: {proposal.category} — {proposal.description[:80]}")
            except Exception as e:
                logger.error(f"[DeliberationGate] Task proposal notification failed: {e}")


async def _check_daily_research_cap(user_id: str) -> bool:
    """Check if we've already dispatched an auto-research today. Returns True if at cap."""
    from sqlalchemy import text as sa_text
    from datetime import date
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
            row = await db.execute(sa_text("""
                SELECT COUNT(*)::int AS cnt
                FROM agent_run_log
                WHERE user_id = :uid
                  AND source IN ('deliberation_research', 'consolidation_research')
                  AND run_at >= :since
            """), {"uid": user_id, "since": today_start})
            count = row.scalar() or 0
            return count >= 1
    except Exception as e:
        logger.warning(f"[DeliberationGate] Daily research cap check failed: {e}")
        return False  # Allow if we can't check


async def _research_should_skip(user_id: str, proposal):
    """Guard the auto-research path so it can't loop.

    Returns a short reason string if this research proposal should NOT be
    auto-dispatched, else None:
      - "daily_cap": an auto-research already went out today. This counts the
        deliberation_task auto-dispatch path too — the original cap only looked
        at the deliberation_research / consolidation_research sources, which is
        exactly why this path looped past the "max 1/day" limit.
      - "duplicate": a closely-matching research task was already attempted in
        the last 3 days (any status), so re-dispatching would just repeat it.
    """
    import difflib
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
            row = await db.execute(sa_text("""
                SELECT COUNT(*)::int AS cnt
                FROM agent_run_log
                WHERE user_id = :uid AND run_at >= :since
                  AND (
                    source IN ('deliberation_research', 'consolidation_research')
                    OR (source = 'deliberation_task'
                        AND actions_taken->>'category' = 'research'
                        AND actions_taken->>'action' = 'auto_dispatched')
                  )
            """), {"uid": user_id, "since": today_start})
            if (row.scalar() or 0) >= 1:
                return "daily_cap"

            topic = (proposal.description or "").strip().lower()
            if not topic:
                return None
            rows = await db.execute(sa_text("""
                SELECT original_query
                FROM background_task
                WHERE user_id = :uid
                  AND created_at >= NOW() - INTERVAL '3 days'
                ORDER BY created_at DESC
                LIMIT 40
            """), {"uid": user_id})
            for r in rows.all():
                prior = (r[0] or "").strip().lower()
                if prior and difflib.SequenceMatcher(None, topic, prior).ratio() >= 0.6:
                    return "duplicate"
    except Exception as e:
        # Fail open — a check failure shouldn't permanently mute autonomy.
        logger.warning(f"[DeliberationGate] research skip-check failed (allowing): {e}")
        return None
    return None


async def _process_research_proposals(
    user_id: str,
    proposals: list,
    summary: dict,
) -> None:
    """Validate and dispatch research proposals from deliberation."""
    # Only process the first proposal (max 1 per deliberation)
    proposal_topic = proposals[0] if proposals else None
    if not proposal_topic:
        return

    # Check daily cap (max 1 auto-research per day across all sources)
    at_cap = await _check_daily_research_cap(user_id)
    if at_cap:
        logger.info(f"[DeliberationGate] Research proposal capped (daily limit reached): {proposal_topic[:80]}")
        summary["research_capped"] += 1
        return

    # Dispatch as a research task
    try:
        from app.services.agent_dispatch import agent_dispatch_service
        from app.main_simple import SessionLocal

        db = None
        try:
            db = SessionLocal()
            result = await agent_dispatch_service.dispatch_task(
                db=db,
                user_id=user_id,
                task_description=f"Research: {proposal_topic}",
                mode="auto",
                notify_on_complete=True,
            )
            summary["research_dispatched"] += 1
            logger.info(
                f"[DeliberationGate] Research auto-dispatched: "
                f"task_id={result.get('task_id')} topic='{proposal_topic[:80]}'"
            )
        finally:
            if db:
                db.close()

        # Write agent_run_log for traceability
        await _write_research_dispatch_log(
            user_id=user_id,
            topic=proposal_topic,
            task_id=result.get("task_id", "unknown"),
            source="deliberation_research",
        )

        # Write journal entry about the research intent
        await _write_research_journal(
            user_id=user_id,
            topic=proposal_topic,
            source="deliberation",
        )

    except Exception as e:
        logger.error(f"[DeliberationGate] Research dispatch failed: {e}")


async def _write_research_dispatch_log(
    user_id: str,
    topic: str,
    task_id: str,
    source: str,
) -> None:
    """Write a research dispatch record to agent_run_log."""
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(sa_text("""
                INSERT INTO agent_run_log
                (user_id, source, run_at, run_duration_ms, context_summary,
                 actions_taken, created_at)
                VALUES (:uid, :source, NOW(), 0, :context_summary,
                        CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "source": source,
                "context_summary": f"Self-directed research dispatched: {topic}"[:2000],
                "actions": json.dumps({
                    "action": "research_dispatched",
                    "task_id": task_id,
                    "topic": topic[:500],
                }),
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Research dispatch log write failed: {e}")


async def _write_research_journal(
    user_id: str,
    topic: str,
    source: str,
) -> None:
    """Write a journal entry about a self-directed research dispatch."""
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(sa_text("""
                INSERT INTO sara_journal (
                    id, user_id, entry_type, content, observations, interpretation,
                    emotional_state, actions_taken, watching_for, conversation_id,
                    context, created_at
                ) VALUES (
                    :id, :user_id, 'deliberation', :content, NULL, NULL,
                    'curious', :actions, NULL, NULL, NULL, NOW()
                )
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "content": (
                    f"I noticed David keeps asking about {topic} -- "
                    f"starting a background research task from {source}."
                )[:2000],
                "actions": f"research_dispatch: {topic}"[:500],
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Research journal write failed: {e}")


async def _dispatch_from_deliberation(user_id: str, proposal: TaskProposal) -> None:
    """Dispatch a task from deliberation via agent_dispatch_service."""
    from app.services.agent_dispatch import agent_dispatch_service
    from app.main_simple import SessionLocal

    db = None
    try:
        db = SessionLocal()
        result = await agent_dispatch_service.dispatch_from_deliberation(
            db=db,
            user_id=user_id,
            description=proposal.description,
            category=proposal.category,
            confidence=proposal.confidence,
            reason=proposal.reason,
        )
        logger.info(
            f"[DeliberationGate] Autonomous dispatch: task_id={result.get('task_id')} "
            f"mode={result.get('mode')} category={proposal.category} "
            f"reason={proposal.reason[:100]}"
        )

        # Write to agent_run_log for traceability
        await _write_task_dispatch_log(
            user_id=user_id,
            task_id=result.get("task_id", "unknown"),
            proposal=proposal,
            auto_executed=True,
        )
    finally:
        if db:
            db.close()


async def _propose_task_to_david(user_id: str, proposal: TaskProposal) -> None:
    """Send a notification proposing a task to David for approval."""
    from app.services.unified_notification import send_notification

    confidence_pct = f"{proposal.confidence:.0%}"
    message = (
        f"{proposal.description}\n\n"
        f"Reason: {proposal.reason}\n"
        f"Confidence: {confidence_pct}"
    )

    await send_notification(
        user_id=user_id,
        title=f"Task suggestion: {proposal.description[:60]}",
        message=message,
        topic=f"task_proposal:{proposal.category}",
        priority="normal",
        source="deliberation",
    )

    await _write_task_dispatch_log(
        user_id=user_id,
        task_id="proposed",
        proposal=proposal,
        auto_executed=False,
    )


async def _write_task_dispatch_log(
    user_id: str,
    task_id: str,
    proposal: TaskProposal,
    auto_executed: bool,
) -> None:
    """Write a task dispatch record to agent_run_log for observability."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    action = "auto_dispatched" if auto_executed else "proposed_to_user"
    thought = (
        f"Task {action}: [{proposal.category}] {proposal.description} "
        f"(confidence={proposal.confidence:.0%}, reason={proposal.reason})"
    )

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(text("""
                INSERT INTO agent_run_log
                (user_id, source, run_at, run_duration_ms, context_summary,
                 actions_taken, created_at)
                VALUES (:uid, 'deliberation_task', NOW(), 0, :context_summary,
                        CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "context_summary": thought[:2000],
                "actions": json.dumps({
                    "action": action,
                    "task_id": task_id,
                    "category": proposal.category,
                    "confidence": proposal.confidence,
                    "description": proposal.description[:500],
                }),
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Task dispatch log write failed: {e}")


async def _deliver_notification(user_id: str, proposal: NotificationProposal) -> None:
    """Deliver a notification through the existing pipeline WITH dedup."""
    import hashlib
    from app.services.unified_notification import send_notification
    from app.db.session import get_async_session_factory

    priority_map = {
        "normal": "normal",
        "high": "high",
        "critical": "max",
    }
    ntfy_priority = priority_map.get(proposal.priority, "default")

    # Build a content-specific topic for proper dedup (not just the category)
    content_hash = hashlib.md5(f"{proposal.title}:{proposal.message[:100]}".encode()).hexdigest()[:12]
    effective_topic = f"{proposal.category}:{content_hash}"

    AsyncSession = get_async_session_factory()
    async with AsyncSession() as db:
        result = await send_notification(
            user_id=user_id,
            title=proposal.title,
            message=proposal.message,
            topic=effective_topic,
            category=proposal.category,
            priority=ntfy_priority,
            source="deliberation",
            db=db,
        )
        await db.commit()
        if result.get("sent"):
            logger.info(f"[DeliberationGate] Sent notification: {proposal.title}")
        else:
            logger.info(f"[DeliberationGate] Notification blocked by pipeline: {result.get('reason')} — {proposal.title}")


async def _execute_home_action(user_id: str, action: HomeActionProposal) -> None:
    """Execute a home control action via ha_control_service."""
    from app.services.ha_control_service import ha_control

    if action.action == "light_control":
        if action.state == "off":
            await ha_control.turn_off_light(action.entity_id)
        else:
            await ha_control.turn_on_light(action.entity_id)
    elif action.action == "lock_control":
        if action.state == "on":  # locked
            await ha_control.lock(action.entity_id)
        else:
            await ha_control.unlock(action.entity_id)
    elif action.action == "switch_control":
        if action.state == "off":
            await ha_control.turn_off_switch(action.entity_id)
        else:
            await ha_control.turn_on_switch(action.entity_id)

    logger.info(f"[DeliberationGate] Executed: {action.action} {action.entity_id} → {action.state} ({action.reason})")


async def _write_journal(user_id: str, result: DeliberationResult) -> None:
    """Write deliberation thought as journal entry."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    # Sara's journal is David-facing: use her first-person journal_note, NOT the
    # analytical `thought` (that stays internal, in agent_run_log). Append only
    # factual action lines. If there's no note and no actions, skip entirely —
    # never dump raw third-person reasoning as a "journal" entry.
    content_parts = []
    if result.journal_note and result.journal_note.strip():
        content_parts.append(result.journal_note.strip())
    if result.notification_proposals:
        titles = [np.title for np in result.notification_proposals]
        content_parts.append(f"Notified you about: {', '.join(titles)}")
    if result.home_actions:
        actions = [f"{a.action}({a.entity_id})" for a in result.home_actions]
        content_parts.append(f"Home actions: {', '.join(actions)}")
    if result.task_proposals:
        tasks = [f"{tp.category}: {tp.description[:80]}" for tp in result.task_proposals]
        content_parts.append(f"Task proposals: {', '.join(tasks)}")

    if not content_parts:
        return

    content = "\n\n".join(content_parts)

    actions_str = ""
    if result.notification_proposals or result.home_actions or result.task_proposals:
        action_items = [f"notified: {np.title}" for np in result.notification_proposals]
        action_items += [f"{a.action}: {a.entity_id}" for a in result.home_actions]
        action_items += [f"task({tp.category}): {tp.description[:60]}" for tp in result.task_proposals]
        actions_str = "; ".join(action_items)

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            # Suppress repetitive journal loops when thought content is effectively unchanged.
            recent_rows = await db.execute(text("""
                SELECT content
                FROM sara_journal
                WHERE user_id = :uid
                  AND entry_type = 'deliberation'
                  AND created_at >= NOW() - INTERVAL '12 hours'
                ORDER BY created_at DESC
                LIMIT 8
            """), {"uid": user_id})
            recent_contents = [r.content for r in recent_rows.fetchall() if r.content]

            has_actions = bool(actions_str or result.notification_proposals or result.home_actions or result.task_proposals)
            too_similar = any(_journal_similarity(content, prior) >= 0.9 for prior in recent_contents)
            if too_similar and not has_actions:
                logger.info("[DeliberationGate] Skipping repetitive journal entry")
                return

            await db.execute(text("""
                INSERT INTO sara_journal (
                    id, user_id, entry_type, content, observations, interpretation,
                    emotional_state, actions_taken, watching_for, conversation_id,
                    context, created_at
                ) VALUES (
                    :id, :user_id, 'deliberation', :content, NULL, NULL,
                    :emotional_state, :actions_taken, :watching_for, NULL, NULL, NOW()
                )
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "content": content[:2000],
                "emotional_state": result.state_update.get("emotional_tone"),
                "actions_taken": actions_str[:500] if actions_str else None,
                "watching_for": result.watching_for[:500] if result.watching_for else None,
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Journal write SQL failed: {e}")


async def _write_run_log(user_id: str, result: DeliberationResult, summary: dict) -> None:
    """Write to agent_run_log for observability."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(text("""
                INSERT INTO agent_run_log
                (user_id, source, run_at, run_duration_ms, context_summary,
                 handoff_note, watching_for, actions_taken, created_at)
                VALUES (:uid, 'deliberation', NOW(), :duration_ms, :context_summary,
                        :handoff, :watching, CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "duration_ms": int((result.duration_seconds or 0) * 1000),
                "context_summary": result.thought[:2000] if result.thought else None,
                "handoff": result.handoff_note[:1000] if result.handoff_note else None,
                "watching": result.watching_for[:500] if result.watching_for else None,
                "actions": json.dumps(summary),
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] agent_run_log write failed: {e}")
