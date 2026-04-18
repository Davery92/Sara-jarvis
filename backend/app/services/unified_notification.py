"""
Unified Notification Pipeline

Single entry point for all notifications with topic-based deduplication.
Replaces scattered push implementations across heartbeat, subconscious,
proactive, and anticipation services.
"""

import logging
import inspect
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default user ID
DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Hardcoded fallbacks for category cooldowns (hours). The values for `checkin`,
# `general`, `calendar`, `email`, and `health` are overridden at runtime by
# `tunable_setting` rows via `_cooldown_for()` below — edit them in the
# Settings UI, not here.
DEFAULT_COOLDOWNS = {
    "calendar": 24.0,
    "weather": 8.0,
    "checkin": 2.0,
    "email": 4.0,
    "security": 0.25,
    "home": 2.0,
    "reminder": 1.0,
    "timer": 0.5,
    "general": 2.0,
    "acs_discovery": 4.0,
    "health": 24.0,
    "fitness": 24.0,
    "wellness": 24.0,
    "system_health": 0.5,
    "calendar_prep": 2.0,
}

# Mapping from category → tunable key. Categories not in this map fall through
# to the hardcoded DEFAULT_COOLDOWNS value.
_TUNABLE_COOLDOWN_KEYS = {
    "checkin": "notification.cooldown.checkin_hours",
    "general": "notification.cooldown.general_hours",
    "calendar": "notification.cooldown.calendar_hours",
    "email": "notification.cooldown.email_hours",
    "health": "notification.cooldown.health_hours",
    "fitness": "notification.cooldown.health_hours",  # share the health knob
    "wellness": "notification.cooldown.health_hours",
}


def _cooldown_for(category: str) -> float:
    """Return effective cooldown (hours) for a category, honoring tunables."""
    fallback = DEFAULT_COOLDOWNS.get(category, 2.0)
    tunable_key = _TUNABLE_COOLDOWN_KEYS.get(category)
    if not tunable_key:
        return fallback
    try:
        from app.services.tunables import get_tunable_float
        return get_tunable_float(tunable_key, fallback)
    except Exception:
        return fallback

# Even when category cooldown is 0, block identical duplicates for a short period.
MIN_EXACT_DEDUP_HOURS = 0.25

# ─── Cached notification preferences ─────────────────────────────
# In-memory cache of per-user notification preferences.
# Structure: {user_id: {"disabled_categories": set, "custom_ban_phrases": list, "loaded_at": float}}
_PREF_CACHE: Dict[str, Dict[str, Any]] = {}
_PREF_CACHE_TTL = 300  # seconds — reload from DB every 5 minutes


async def _load_notification_preferences(user_id: str, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """Load notification preferences from DB (with in-memory cache)."""
    now = time.time()
    cached = _PREF_CACHE.get(user_id)
    if cached and (now - cached["loaded_at"]) < _PREF_CACHE_TTL:
        return cached

    disabled_categories: set = set()
    custom_phrases: list = []

    if db:
        try:
            result = await _db_execute(db, text("""
                SELECT category, enabled, custom_ban_phrases
                FROM notification_preference
                WHERE user_id = :user_id
            """), {"user_id": user_id})
            rows = result.fetchall()
            for row in rows:
                if not row.enabled:
                    disabled_categories.add(row.category.lower())
                if row.custom_ban_phrases:
                    phrases = row.custom_ban_phrases if isinstance(row.custom_ban_phrases, list) else []
                    custom_phrases.extend(phrases)
        except Exception as e:
            # Table may not exist yet on older deployments — fail open
            logger.debug(f"notification_preference table read failed (OK if not migrated): {e}")

    entry = {
        "disabled_categories": disabled_categories,
        "custom_ban_phrases": custom_phrases,
        "loaded_at": now,
    }
    _PREF_CACHE[user_id] = entry
    return entry


def invalidate_notification_pref_cache(user_id: str) -> None:
    """Invalidate the cached preferences for a user (called after settings update)."""
    _PREF_CACHE.pop(user_id, None)


async def _check_notification_ban(
    user_id: str,
    title: str,
    message: str,
    category: str,
    db: Optional[AsyncSession] = None,
) -> Optional[str]:
    """
    Check if a notification should be banned based on:
    1. Static hard-ban list in deliberation_gate
    2. Dynamic per-user category toggles from notification_preference table
    3. User custom ban phrases

    Returns ban reason or None.
    """
    from app.services.deliberation_gate import is_notification_banned

    # Load user prefs (cached)
    prefs = await _load_notification_preferences(user_id, db)

    # Merge dynamic disabled categories into the check
    # If the category is disabled in user preferences, reject immediately
    if category.lower() in prefs["disabled_categories"]:
        return f"User disabled category: {category}"

    # Static ban list + user custom phrases
    return is_notification_banned(
        title=title,
        message=message,
        category=category,
        custom_ban_phrases=prefs["custom_ban_phrases"],
    )


async def send_notification(
    user_id: str,
    title: str,
    message: str,
    priority: str = "normal",
    topic: Optional[str] = None,
    category: str = "general",
    source: str = "unified_heartbeat",
    cooldown_hours: Optional[float] = None,
    agent_run_id: Optional[int] = None,
    db: Optional[AsyncSession] = None,
    _bypass_attention: bool = False,
    _attention_item_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a notification through the unified pipeline with topic-based dedup.

    Args:
        user_id: Target user ID
        title: Notification title
        message: Notification body
        priority: "low", "normal", "important", "high", "urgent", or "critical"
        topic: Dedup key, e.g. "calendar:gymnastics_7pm_20260205"
        category: Notification category for cooldown lookup
        source: Which system sent this
        cooldown_hours: Override default cooldown for this category
        agent_run_id: FK to agent_run_log if sent from a heartbeat run
        db: AsyncSession (required for dedup checks)
        _bypass_attention: Internal flag to prevent recursion from route_through_attention_queue
        _attention_item_id: Attention item FK to link in notification_log

    Returns:
        Dict with {sent: bool, reason: str, ...}
    """
    priority = _normalize_priority(priority)

    # Ensure we always have a session. Without this, callers that forget
    # the db kwarg silently skip dedup AND logging — which is how the
    # "hourly push about the same email" bug landed in production: a
    # Celery task at :43 past each hour called us with db=None, dedup was
    # skipped, notification_log wasn't written, and the outer cooldown
    # never kicked in. Opening our own session here makes dedup the
    # default instead of an opt-in.
    _owned_session = False
    if db is None:
        try:
            from app.db.session import get_async_session_factory
            _factory = get_async_session_factory()
            db = _factory()
            await db.__aenter__()
            _owned_session = True
        except Exception as exc:
            logger.warning(
                f"send_notification could not open fallback session: {exc}; "
                "proceeding without dedup/logging"
            )
            db = None

    try:
        result = await _send_notification_impl(
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            topic=topic,
            category=category,
            source=source,
            cooldown_hours=cooldown_hours,
            agent_run_id=agent_run_id,
            db=db,
            _bypass_attention=_bypass_attention,
            _attention_item_id=_attention_item_id,
        )
        # AsyncSession does not auto-commit — if we opened this session
        # ourselves, the caller isn't going to commit for us, so the
        # dedup log row + attention item would roll back on exit and
        # next hour's call would not see them as dupes. Explicit commit.
        if _owned_session and db is not None:
            try:
                await db.commit()
            except Exception as exc:
                logger.warning(f"send_notification auto-session commit failed: {exc}")
        return result
    finally:
        if _owned_session and db is not None:
            try:
                await db.__aexit__(None, None, None)
            except Exception:
                pass


async def _send_notification_impl(
    *,
    user_id: str,
    title: str,
    message: str,
    priority: str,
    topic: Optional[str],
    category: str,
    source: str,
    cooldown_hours: Optional[float],
    agent_run_id: Optional[int],
    db: Optional[AsyncSession],
    _bypass_attention: bool,
    _attention_item_id: Optional[str],
) -> Dict[str, Any]:
    # ── Engagement-based priority adjustment ──
    # If David consistently ignores a category, lower priority; if he engages, boost
    if db and category not in ("system_health", "security"):
        try:
            eng_result = await db.execute(text("""
                SELECT count(*) FILTER (WHERE sent = true) as sent,
                       count(*) FILTER (WHERE engaged = true) as engaged
                FROM notification_log
                WHERE user_id = :uid AND category = :cat
                  AND sent_at > NOW() - INTERVAL '14 days'
            """), {"uid": user_id, "cat": category})
            eng_row = eng_result.fetchone()
            if eng_row and eng_row[0] >= 5:  # Only adjust after 5+ sends
                eng_rate = eng_row[1] / eng_row[0]
                if eng_rate < 0.10 and priority in ("normal", "low"):
                    priority = "low"  # Demote rarely-engaged categories
                    logger.debug(f"Notification priority demoted for {category} (engagement={eng_rate:.0%})")
                elif eng_rate > 0.60 and priority == "low":
                    priority = "normal"  # Promote highly-engaged categories
        except Exception:
            pass  # Don't block notifications on analytics failure

    # ── Notification tuner check: suppress categories with very low engagement ──
    try:
        from app.services.notification_tuner import get_tuning_for_category
        tuning_action = get_tuning_for_category(user_id, category)
        if tuning_action == "suppress" and priority not in ("urgent", "critical"):
            logger.info(f"Notification suppressed by tuner: {category} | title={title[:60]}")
            return {"sent": False, "reason": "tuner_suppressed", "category": category}
        elif tuning_action == "double_cooldown":
            cooldown_hours = (cooldown_hours or _cooldown_for(category)) * 2
    except Exception:
        pass

    # ── Ban check: reject health/fitness/banned notifications before any delivery ──
    ban_reason = await _check_notification_ban(user_id, title, message, category, db)
    if ban_reason:
        logger.info(f"Notification banned at pipeline entry: {ban_reason} | title={title[:60]}")
        if db:
            await _log_notification(
                db, user_id, topic or f"{category}:{_hash_topic(title, message)}",
                category, title, message, priority, source, agent_run_id,
                0, sent=False, dedup_blocked=True,
            )
        return {"sent": False, "reason": "banned_topic", "ban_reason": ban_reason}

    # Route through attention queue when enabled (Phase 2 — Cortana Evolution)
    if not _bypass_attention and db:
        try:
            from app.core.config import settings
            if getattr(settings, 'autonomy_attention_enabled', False):
                return await route_through_attention_queue(
                    user_id=user_id, title=title, message=message,
                    priority=priority, category=category, source=source,
                    dedupe_key=topic, db=db,
                )
        except Exception as e:
            logger.debug(f"Attention queue routing failed, falling through: {e}")

    effective_cooldown = cooldown_hours if cooldown_hours is not None else _cooldown_for(category)
    effective_topic = topic or f"{category}:{_hash_topic(title, message)}"

    # Dedup check:
    # - normal path: category cooldown window
    # - fallback safety net: short exact-topic window even when category cooldown is 0
    if db:
        dedup_window = effective_cooldown if effective_cooldown > 0 else MIN_EXACT_DEDUP_HOURS
        include_category_limits = effective_cooldown > 0
        is_dup = await _check_dedup(
            db,
            user_id,
            effective_topic,
            dedup_window,
            include_category_limits=include_category_limits,
        )
        if is_dup:
            logger.info(f"Notification dedup blocked: topic={effective_topic} cooldown={dedup_window}h")
            # Log the blocked attempt
            await _log_notification(
                db, user_id, effective_topic, category, title, message,
                priority, source, agent_run_id, dedup_window,
                sent=False, dedup_blocked=True,
                attention_item_id=_attention_item_id,
            )
            return {"sent": False, "reason": "dedup", "topic": effective_topic}

    # Try desktop delivery via WebSocket first (real-time, no phone buzz)
    desktop_sent = False
    try:
        from app.services.command_router import command_router, CommandMessage, CommandType
        from app.db.session import SessionLocal
        ws_db = SessionLocal()
        try:
            connected = command_router.get_connected_devices(user_id)
            if connected:
                cmd = CommandMessage(
                    command_type=CommandType.SHOW_NOTIFICATION,
                    payload={"title": title, "message": message, "priority": priority, "source": source}
                )
                desktop_sent = await command_router.send_command(ws_db, user_id, cmd)
                if desktop_sent:
                    logger.info(f"Notification delivered via desktop WebSocket: {title[:50]}")
        finally:
            ws_db.close()
    except Exception as e:
        logger.debug(f"Desktop WebSocket delivery skipped: {e}")

    # Get push tokens
    tokens = await _get_push_tokens(db, user_id) if db else await _get_push_tokens_sync(user_id)

    if not tokens and not desktop_sent:
        logger.warning(f"No push tokens for user {user_id}")
        return {"sent": False, "reason": "no_tokens"}

    # Log optimistically before push so we can include notification_id in payload
    notification_id = None
    if db:
        logged_cooldown = effective_cooldown if effective_cooldown > 0 else MIN_EXACT_DEDUP_HOURS
        notification_id = await _log_notification(
            db, user_id, effective_topic, category, title, message,
            priority, source, agent_run_id, logged_cooldown,
            sent=True, dedup_blocked=False,
            attention_item_id=_attention_item_id,
        )

    # Send via mobile push only if desktop delivery failed or wasn't available
    success = desktop_sent
    if tokens and not desktop_sent:
        push_success = await _send_push(
            tokens, title, message, priority, source,
            notification_id=notification_id,
            category=category,
        )
        success = success or push_success

    if not success:
        # Mark log as unsent if push failed
        if notification_id and db:
            try:
                await _db_execute(db, text("""
                    UPDATE notification_log SET sent = FALSE WHERE id = :id
                """), {"id": notification_id})
            except Exception:
                pass
        return {"sent": False, "reason": "push_failed"}

    logger.info(f"Notification sent: topic={effective_topic} title={title[:50]}")
    return {
        "sent": True,
        "topic": effective_topic,
        "notification_id": notification_id,
    }


async def send_consolidated_notification(
    user_id: str,
    notifications: List[Dict[str, Any]],
    source: str = "unified_heartbeat",
    agent_run_id: Optional[int] = None,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Send multiple queued notifications as a single consolidated push.
    Each individual notification still gets dedup-checked and logged.

    When AUTONOMY_ATTENTION_ENABLED, each notification is routed through
    the attention queue. Low/normal items become queue-only; high+ items
    get pushed AND queued.

    Args:
        notifications: List of dicts with keys: title, message, priority, topic, category

    Returns:
        Dict with results for each notification and the consolidated send result.
    """
    if not notifications:
        return {"sent": False, "reason": "empty_queue"}

    # Check if attention queue routing is active
    attention_enabled = False
    try:
        from app.core.config import settings
        attention_enabled = getattr(settings, 'autonomy_attention_enabled', False) and db is not None
    except Exception:
        pass

    if attention_enabled:
        # Route each notification individually through the attention queue
        results = []
        any_sent = False
        for notif in notifications:
            r = await route_through_attention_queue(
                user_id=user_id,
                title=notif["title"],
                message=notif["message"],
                priority=notif.get("priority", "normal"),
                category=notif.get("category", "general"),
                source=source,
                dedupe_key=notif.get("topic"),
                db=db,
            )
            results.append(r)
            if r.get("sent"):
                any_sent = True
        return {
            "sent": any_sent,
            "consolidated_count": len(notifications),
            "routed_through_attention": True,
            "details": results,
        }

    # Filter through ban check + dedup
    to_send = []
    results = []
    for notif in notifications:
        topic = notif.get("topic") or f"{notif.get('category', 'general')}:{_hash_topic(notif['title'], notif['message'])}"
        category = notif.get("category", "general")
        normalized_priority = _normalize_priority(notif.get("priority", "normal"))

        # Ban check for each individual notification
        ban_reason = await _check_notification_ban(user_id, notif["title"], notif["message"], category, db)
        if ban_reason:
            logger.info(f"Consolidated notif banned: {ban_reason} | title={notif['title'][:60]}")
            results.append({"topic": topic, "sent": False, "reason": "banned_topic", "ban_reason": ban_reason})
            continue

        configured_cooldown = notif.get("cooldown_hours")
        if configured_cooldown is None:
            configured_cooldown = _cooldown_for(category)
        dedup_window = configured_cooldown if configured_cooldown > 0 else MIN_EXACT_DEDUP_HOURS
        include_category_limits = configured_cooldown > 0

        if db and dedup_window > 0:
            is_dup = await _check_dedup(
                db, user_id, topic, dedup_window, include_category_limits=include_category_limits
            )
            if is_dup:
                await _log_notification(
                    db, user_id, topic, category, notif["title"], notif["message"],
                    normalized_priority, source, agent_run_id, dedup_window,
                    sent=False, dedup_blocked=True
                )
                results.append({"topic": topic, "sent": False, "reason": "dedup"})
                continue

        to_send.append({
            **notif,
            "topic": topic,
            "category": category,
            "cooldown": dedup_window,
            "priority": normalized_priority,
        })

    if not to_send:
        return {"sent": False, "reason": "all_deduped", "details": results}

    # Build consolidated message
    if len(to_send) == 1:
        title = to_send[0]["title"]
        body = to_send[0]["message"]
        final_priority = to_send[0].get("priority", "normal")
    else:
        title = f"Sara ({len(to_send)} things)"
        body_parts = []
        for n in to_send:
            t = n["title"][:50]
            m = n["message"][:100]
            body_parts.append(f"- {t}: {m}")
        body = "\n".join(body_parts)
        final_priority = "high" if any(
            n.get("priority") in ("high", "urgent", "critical")
            for n in to_send
        ) else "normal"

    # Send
    tokens = await _get_push_tokens(db, user_id) if db else await _get_push_tokens_sync(user_id)
    if not tokens:
        return {"sent": False, "reason": "no_tokens"}

    success = await _send_push(tokens, title, body, final_priority, source, category=category)

    # Log each notification
    if db:
        for n in to_send:
            await _log_notification(
                db, user_id, n["topic"], n["category"], n["title"], n["message"],
                n.get("priority", "normal"), source, agent_run_id, n["cooldown"],
                sent=success, dedup_blocked=False
            )

    results.extend([{"topic": n["topic"], "sent": success} for n in to_send])
    return {
        "sent": success,
        "consolidated_count": len(to_send),
        "title": title,
        "details": results,
    }


async def send_notification_with_interruptibility(
    user_id: str,
    title: str,
    message: str,
    urgency: str = "normal",
    priority: str = "normal",
    topic: Optional[str] = None,
    category: str = "general",
    source: str = "system",
    cooldown_hours: Optional[float] = None,
    agent_run_id: Optional[int] = None,
    db: Optional[AsyncSession] = None,
    deliver_by_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Interruptibility-aware notification routing.

    Checks David's current interruptibility score and either:
    - Delivers immediately (urgency <= interruptibility)
    - Queues for later delivery (urgency > interruptibility)
    - Always delivers CRITICAL urgency

    Args:
        urgency: "silent", "normal", "important", "urgent", "critical"
        deliver_by_minutes: Max minutes to hold before forcing delivery (None = no limit)
        (all other args same as send_notification)

    Returns:
        Dict with {sent: bool, reason: str, queued: bool, ...}
    """
    from app.services.interruptibility import (
        Urgency, compute_interruptibility, notification_queue, QueuedNotification,
    )
    from app.services.activity_state_machine import activity_state_machine

    try:
        urgency_enum = Urgency(urgency)
    except ValueError:
        urgency_enum = Urgency.NORMAL

    # CRITICAL always sends
    if urgency_enum == Urgency.CRITICAL:
        result = await send_notification(
            user_id=user_id, title=title, message=message,
            priority="high", topic=topic, category=category,
            source=source, cooldown_hours=cooldown_hours,
            agent_run_id=agent_run_id, db=db,
        )
        result["urgency"] = "critical"
        result["queued"] = False
        return result

    # Get current interruptibility
    current_activity = activity_state_machine.current
    interruptibility = compute_interruptibility(activity=current_activity)
    decision = interruptibility.delivery_decision(urgency_enum)

    if decision == "deliver":
        # Map urgency to push priority
        push_priority = "high" if urgency_enum in (Urgency.URGENT, Urgency.IMPORTANT) else priority
        result = await send_notification(
            user_id=user_id, title=title, message=message,
            priority=push_priority, topic=topic, category=category,
            source=source, cooldown_hours=cooldown_hours,
            agent_run_id=agent_run_id, db=db,
        )
        result["urgency"] = urgency
        result["interruptibility"] = interruptibility.score
        result["queued"] = False
        return result

    elif decision == "queue":
        # Queue for later
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        import uuid

        deliver_by = None
        if deliver_by_minutes:
            deliver_by = datetime.now(ZoneInfo("America/New_York")) + timedelta(minutes=deliver_by_minutes)

        queued = QueuedNotification(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            urgency=urgency_enum,
            category=category,
            topic=topic or f"{category}:{title[:30]}",
            queued_at=datetime.now(ZoneInfo("America/New_York")),
            deliver_by=deliver_by,
            source=source,
        )
        notification_queue.enqueue(queued)

        logger.info(
            f"Notification queued (interruptibility={interruptibility.score:.2f}, "
            f"urgency={urgency}, activity={current_activity.state.value}): {title[:50]}"
        )
        return {
            "sent": False,
            "queued": True,
            "reason": f"queued (interruptibility={interruptibility.score:.2f}, state={current_activity.state.value})",
            "urgency": urgency,
            "interruptibility": interruptibility.score,
            "deliver_by": deliver_by.isoformat() if deliver_by else None,
        }

    else:  # suppress
        logger.info(
            f"Notification suppressed (interruptibility={interruptibility.score:.2f}, "
            f"urgency={urgency}): {title[:50]}"
        )
        return {
            "sent": False,
            "queued": False,
            "reason": f"suppressed (interruptibility={interruptibility.score:.2f})",
            "urgency": urgency,
            "interruptibility": interruptibility.score,
        }


async def flush_notification_queue(
    user_id: str,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Flush any queued notifications that can now be delivered.
    Called when interruptibility rises (e.g., David becomes active).

    Returns summary of what was delivered.
    """
    from app.services.interruptibility import notification_queue, compute_interruptibility
    from app.services.activity_state_machine import activity_state_machine

    current_activity = activity_state_machine.current
    interruptibility = compute_interruptibility(activity=current_activity)

    deliverable = notification_queue.flush_deliverable(interruptibility.score)

    if not deliverable:
        return {"flushed": 0, "pending": notification_queue.pending_count()}

    # Send as consolidated notification
    notifs_to_send = [
        {
            "title": n.title,
            "message": n.message,
            "priority": "high" if n.urgency.value in ("urgent", "important") else "normal",
            "topic": n.topic,
            "category": n.category,
        }
        for n in deliverable
    ]

    result = await send_consolidated_notification(
        user_id=user_id,
        notifications=notifs_to_send,
        source="queue_flush",
        db=db,
    )

    logger.info(f"Flushed {len(deliverable)} queued notifications (score={interruptibility.score:.2f})")
    return {
        "flushed": len(deliverable),
        "pending": notification_queue.pending_count(),
        "result": result,
    }


async def route_through_attention_queue(
    user_id: str,
    title: str,
    message: str,
    priority: str = "normal",
    category: str = "general",
    source: str = "unified_agent",
    dedupe_key: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Route a notification through the attention queue (Phase 2 — Cortana Evolution).

    Priority normal/low → create attention item only.
    Priority important/high/urgent/critical → create item AND send push.

    Behind AUTONOMY_ATTENTION_ENABLED flag — when off, sends directly.
    """
    try:
        from app.core.config import settings
        attention_enabled = getattr(settings, 'autonomy_attention_enabled', False)
    except Exception:
        attention_enabled = False

    priority = _normalize_priority(priority)

    if not attention_enabled or not db:
        # Feature off — send directly (bypass attention to avoid recursion)
        return await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, topic=dedupe_key, category=category, source=source, db=db,
            _bypass_attention=True,
        )

    from app.services.autonomy.attention_queue import attention_queue

    attention_payload = _build_attention_payload(
        title=title,
        message=message,
        category=category,
        source=source,
        payload=payload,
    )

    # Always create attention item
    item_id = await attention_queue.create_item(
        db=db, user_id=user_id, title=title, body=message,
        category=category, priority=priority, source=source,
        dedupe_key=dedupe_key, payload=attention_payload,
    )

    # If attention queue persistence is unavailable (e.g., missing table/migration),
    # fail open to direct delivery rather than silently dropping low/normal notices.
    if not item_id:
        logger.warning(
            "Attention queue unavailable for notification; falling back to direct send "
            f"(category={category}, priority={priority}, topic={dedupe_key})"
        )
        return await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, topic=dedupe_key, category=category, source=source, db=db,
            _bypass_attention=True,
        )

    # High priority and above: also send push (bypass attention to avoid recursion)
    if priority in ("high", "urgent", "critical"):
        result = await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, topic=dedupe_key, category=category, source=source, db=db,
            _bypass_attention=True,
            _attention_item_id=item_id,
        )
        result["attention_item_id"] = item_id
        result["routed_through_attention"] = True
        return result

    return {
        "sent": False,
        "attention_item_id": item_id,
        "routed_through_attention": True,
        "reason": f"Low/normal priority routed to attention queue",
    }


async def get_todays_notifications(
    db: AsyncSession,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Get all notifications sent today for context injection."""
    result = await _db_execute(db, text("""
        SELECT topic, category, title, message, priority, source, sent_at, sent, dedup_blocked
        FROM notification_log
        WHERE user_id = :user_id
          AND sent_at >= CURRENT_DATE
        ORDER BY sent_at DESC
    """), {"user_id": user_id})

    rows = result.fetchall()
    return [
        {
            "topic": r.topic,
            "category": r.category,
            "title": r.title,
            "message": r.message,
            "priority": r.priority,
            "source": r.source,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "sent": r.sent,
            "dedup_blocked": r.dedup_blocked,
        }
        for r in rows
    ]


# ─── Internal helpers ─────────────────────────────────────────────


def _hash_topic(title: str, message: str) -> str:
    """Create a simple hash for dedup when no explicit topic is given."""
    import hashlib
    content = f"{title}:{message[:100]}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _normalize_priority(priority: Optional[str]) -> str:
    """Normalize priority labels across callers."""
    value = (priority or "normal").strip().lower()
    mapping = {
        "low": "low",
        "normal": "normal",
        "default": "normal",
        "medium": "normal",
        "high": "high",
        "important": "high",
        "urgent": "urgent",
        "critical": "critical",
    }
    return mapping.get(value, "normal")


def _default_attention_actions(
    title: str,
    message: str,
    category: str,
    payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Generate contextual action buttons per category for attention queue items."""
    actions: List[Dict[str, Any]] = []
    has_chat = False
    payload = payload or {}

    # Extract URLs from payload for potential open_url action
    item_url = payload.get("url") or payload.get("link") or payload.get("original_url")

    if category == "calendar":
        actions.extend([
            {"id": "open_calendar", "label": "Open calendar", "kind": "navigate", "target": "calendar"},
            {"id": "snooze_10m", "label": "Snooze 10m", "kind": "snooze", "minutes": 10},
            {"id": "snooze_30m", "label": "Snooze 30m", "kind": "snooze", "minutes": 30},
        ])
    elif category == "checkin":
        actions.append({"id": "reply", "label": "Reply to Sara", "kind": "chat", "prompt": f"Help me handle this: {title}"})
        actions.append({"id": "snooze_1h", "label": "Snooze 1h", "kind": "snooze", "minutes": 60})
        has_chat = True
    elif category == "reminder":
        actions.extend([
            {"id": "mark_done", "label": "Mark done", "kind": "complete"},
            {"id": "snooze_30m", "label": "Snooze 30m", "kind": "snooze", "minutes": 30},
            {"id": "add_calendar", "label": "Add to calendar", "kind": "add_calendar"},
        ])
    elif category == "email":
        actions.append({"id": "open_email", "label": "Open email", "kind": "navigate", "target": "email"})
        if item_url:
            actions.append({"id": "open_link", "label": "Open link", "kind": "open_url", "url": item_url})
        actions.append({"id": "remind_me", "label": "Remind me", "kind": "add_reminder", "default_minutes": 60})
    elif category == "security":
        actions.append({"id": "details", "label": "Details", "kind": "chat", "prompt": f"Tell me more about this security event: {title}"})
        has_chat = True
    elif category == "home":
        actions.append({"id": "ask_sara", "label": "Ask Sara", "kind": "chat", "prompt": f"Help me with this home event: {title}"})
        has_chat = True
    elif category in ("health", "fitness", "wellness"):
        actions.append({"id": "discuss", "label": "Discuss", "kind": "chat", "prompt": f"Help me with: {title}"})
        actions.append({"id": "remind_later", "label": "Remind me later", "kind": "add_reminder", "default_minutes": 120})
        has_chat = True
    elif category == "weather":
        actions.append({"id": "remind_me", "label": "Remind me", "kind": "add_reminder", "default_minutes": 60})
    elif category == "deferred_action":
        actions.append({"id": "do_now", "label": "Do now", "kind": "chat", "prompt": f"Let's do this now: {title}"})
        actions.append({"id": "snooze_1h", "label": "Snooze 1h", "kind": "snooze", "minutes": 60})
        actions.append({"id": "set_reminder", "label": "Set reminder", "kind": "add_reminder", "default_minutes": 60})
        has_chat = True
    else:
        # general / unknown
        actions.append({"id": "discuss", "label": "Discuss", "kind": "chat", "prompt": f"Help me handle this: {title}"})
        actions.append({"id": "remind_me", "label": "Remind me", "kind": "add_reminder", "default_minutes": 60})
        has_chat = True

    # Universal tail: Ask Sara (if no chat action yet) + Done
    if not has_chat:
        actions.append({"id": "ask_sara", "label": "Ask Sara", "kind": "chat", "prompt": f"Help me with: {title}"})
    actions.append({"id": "done", "label": "Done", "kind": "complete"})

    return actions


def _build_attention_payload(
    title: str,
    message: str,
    category: str,
    source: str,
    payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Ensure attention items carry actionable payload metadata."""
    merged: Dict[str, Any] = dict(payload or {})
    merged.setdefault("title", title)
    merged.setdefault("message", message)
    merged.setdefault("category", category)
    merged.setdefault("source", source)

    actions = merged.get("actions")
    if not isinstance(actions, list) or not actions:
        merged["actions"] = _default_attention_actions(title, message, category, payload=merged)

    return merged


async def _check_dedup(
    db: AsyncSession,
    user_id: str,
    topic: str,
    cooldown_hours: float,
    include_category_limits: bool = True,
) -> bool:
    """Check if a notification with this topic OR same category was sent within the cooldown window."""
    # Exact topic match check
    result = await _db_execute(db, text("""
        SELECT COUNT(*) FROM notification_log
        WHERE user_id = :user_id
          AND topic = :topic
          AND sent = TRUE
          AND sent_at > NOW() - MAKE_INTERVAL(secs => :cooldown_secs)
    """), {
        "user_id": user_id,
        "topic": topic,
        "cooldown_secs": cooldown_hours * 3600,
    })
    count = result.scalar() or 0
    if count > 0:
        return True

    # Category-level rate limit: prevent LLM from varying topic names for the same issue
    # Extract category prefix from topic (e.g. "home" from "home:ecobee_xyz")
    category = topic.split(":")[0] if ":" in topic else topic
    category_limits = {
        "home": (3, 6.0),          # max 3 per 6 hours
        "security": (4, 6.0),      # max 4 per 6 hours
        "checkin": (1, 6.0),       # max 1 per 6 hours
        "weather": (2, 8.0),       # max 2 per 8 hours
        "health": (1, 24.0),       # max 1 per 24 hours
        "fitness": (1, 24.0),      # max 1 per 24 hours
        "wellness": (1, 24.0),     # max 1 per 24 hours
        "acs_discovery": (1, 4.0), # max 1 per 4 hours — finalization consolidates
    }
    if include_category_limits and category in category_limits:
        max_count, window_hours = category_limits[category]
        result = await _db_execute(db, text("""
            SELECT COUNT(*) FROM notification_log
            WHERE user_id = :user_id
              AND category = :category
              AND sent = TRUE
              AND sent_at > NOW() - MAKE_INTERVAL(secs => :window_secs)
        """), {
            "user_id": user_id,
            "category": category,
            "window_secs": window_hours * 3600,
        })
        cat_count = result.scalar() or 0
        if cat_count >= max_count:
            logger.info(f"Category rate limit hit: {category} sent {cat_count}/{max_count} in {window_hours}h")
            return True

    return False


async def _log_notification(
    db: AsyncSession,
    user_id: str,
    topic: str,
    category: str,
    title: str,
    message: str,
    priority: str,
    source: str,
    agent_run_id: Optional[int],
    cooldown_hours: float,
    sent: bool,
    dedup_blocked: bool,
    attention_item_id: Optional[str] = None,
) -> Optional[int]:
    """Log a notification attempt to notification_log."""
    result = await _db_execute(db, text("""
        INSERT INTO notification_log
        (user_id, topic, category, title, message, priority, source,
         agent_run_id, cooldown_hours, sent, dedup_blocked, sent_at,
         attention_item_id)
        VALUES
        (:user_id, :topic, :category, :title, :message, :priority, :source,
         :agent_run_id, :cooldown_hours, :sent, :dedup_blocked, NOW(),
         CAST(:attention_item_id AS uuid))
        RETURNING id
    """), {
        "user_id": user_id,
        "topic": topic,
        "category": category,
        "title": title[:500],
        "message": message[:2000] if message else None,
        "priority": priority,
        "source": source,
        "agent_run_id": agent_run_id,
        "cooldown_hours": cooldown_hours,
        "sent": sent,
        "dedup_blocked": dedup_blocked,
        "attention_item_id": attention_item_id,
    })
    row = result.fetchone()
    return row[0] if row else None


async def _get_push_tokens(db: AsyncSession, user_id: str) -> List[str]:
    """Get active push tokens using async session."""
    result = await _db_execute(db, text("""
        SELECT DISTINCT token FROM push_token
        WHERE user_id = :user_id AND is_active = true
        ORDER BY token
    """), {"user_id": user_id})
    return [r.token for r in result.fetchall()]


async def _get_push_tokens_sync(user_id: str) -> List[str]:
    """Fallback: get push tokens with the shared sync session factory."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT DISTINCT token FROM push_token
            WHERE user_id = :user_id AND is_active = true
            ORDER BY token
        """), {"user_id": user_id}).fetchall()
        return [r.token for r in result]
    finally:
        db.close()


async def _send_push(
    tokens: List[str],
    title: str,
    body: str,
    priority: str = "normal",
    source: str = "unified_heartbeat",
    notification_id: Optional[int] = None,
    category: str = "general",
) -> bool:
    """Send mobile push notification to all of the user's device tokens."""
    unique_tokens = [t for t in dict.fromkeys(tokens) if t]
    if not unique_tokens:
        return False

    normalized_priority = _normalize_priority(priority)
    push_priority = "high" if normalized_priority in ("high", "urgent", "critical") else "default"
    push_data = {
        "type": "heartbeat" if source == "unified_heartbeat" else source,
        "priority": normalized_priority,
        "title": title,
        "message": body,
        "category": category,
    }
    if notification_id is not None:
        push_data["notification_id"] = notification_id

    # Map category to interactive notification category id
    push_category_map = {
        "checkin": "MORNING_CHECKIN",
        "acs_discovery": "ACS_DISCOVERY",
        "calendar_prep": "SARA_INSIGHT",
        "system_health": "GENERAL_NUDGE",
    }
    push_category_id = push_category_map.get(category, "GENERAL_NUDGE")

    messages = [
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": push_data,
            "priority": push_priority,
            "categoryId": push_category_id,
            "_contentAvailable": True,
            "badge": 1,
        }
        for token in unique_tokens
    ]

    try:
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
                logger.info(f"Push sent to {len(unique_tokens)} token(s): {title[:50]}")
                return True
            else:
                logger.error(f"Push failed: {response.status_code} - {response.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Push error: {e}")
        return False


async def _db_execute(db: Any, query, params: Dict[str, Any]):
    """
    Execute SQL against either AsyncSession or sync Session.
    This lets callers pass whichever session type they already have.
    """
    result = db.execute(query, params)
    if inspect.isawaitable(result):
        return await result
    return result
