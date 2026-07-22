"""
Unified Notification Pipeline

Single entry point for all notifications with topic-based deduplication.
Replaces scattered push implementations across heartbeat, subconscious,
proactive, and anticipation services.
"""

import asyncio
import logging
import inspect
import json
import os
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

# Canonical spelling for every category this pipeline knows about, keyed by
# the category string with underscores/dashes stripped. Every cooldown/cap/
# tunable in this module keys on the canonical spelling below — an alias
# (e.g. "check_in") silently bypassed all of it because it never matched any
# lookup. Normalize once at ingestion instead of trusting every caller.
_CANONICAL_CATEGORIES = (
    "checkin", "general", "calendar", "calendar_prep", "email", "health",
    "fitness", "wellness", "weather", "security", "home", "reminder", "timer",
    "acs_discovery", "system_health", "deferred_action", "background_task",
    "thread_followup", "automation",
)
_CATEGORY_ALIAS_MAP = {c.lower().replace("_", "").replace("-", ""): c for c in _CANONICAL_CATEGORIES}


def _normalize_category(category: str) -> str:
    """Map a category alias (e.g. "check_in") to its canonical spelling ("checkin")."""
    if not category:
        return category
    stripped = category.lower().replace("_", "").replace("-", "")
    return _CATEGORY_ALIAS_MAP.get(stripped, category)


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

    # C3 rhythm_forecaster: a high day-level anomaly score means today
    # deviates from David's norm — routine-based nudges assume a normal
    # day, so quiet them rather than nag about a routine that doesn't
    # apply today. Only gates routine/habit-style categories, never
    # meeting/urgent/general sends.
    if category.lower() in ("checkin", "followup") and db:
        try:
            from app.db.base import SessionLocal
            from app.services.daily_rhythm import compute_daily_anomaly_score

            def _check_anomaly():
                with SessionLocal() as sync_db:
                    return compute_daily_anomaly_score(sync_db, user_id)

            anomaly = await asyncio.to_thread(_check_anomaly)
            if anomaly and anomaly["anomaly_score"] >= 0.8:
                return f"Anomalous day (score={anomaly['anomaly_score']}) — quieting routine nudges"
        except Exception as e:
            logger.debug(f"anomaly check skipped: {e}")

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
    _bypass_ban: bool = False,
    _bypass_desktop: bool = False,
    _attention_item_id: Optional[str] = None,
    extra_push_data: Optional[Dict[str, Any]] = None,
    overlay: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    _skip_phrasing: bool = False,
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
        overlay: Optional {"kind": "report", "payload": {...}} — when set, the
            desktop toast becomes clickable and opens that overlay (A2).

    Returns:
        Dict with {sent: bool, reason: str, ...}
    """
    priority = _normalize_priority(priority)
    category = _normalize_category(category)

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
            _bypass_ban=_bypass_ban,
            _bypass_desktop=_bypass_desktop,
            _attention_item_id=_attention_item_id,
            _skip_phrasing=_skip_phrasing,
            extra_push_data=extra_push_data,
            overlay=overlay,
            payload=payload,
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
    _bypass_ban: bool,
    _bypass_desktop: bool = False,
    _attention_item_id: Optional[str] = None,
    extra_push_data: Optional[Dict[str, Any]] = None,
    overlay: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    _skip_phrasing: bool = False,
) -> Dict[str, Any]:
    # SARA_UNLEASHED Phase T.3: the inline engagement-priority-adjuster that
    # used to live here is deleted — it only ever toggled between "normal"
    # and "low", and since route_through_attention_queue's learned buzz
    # decision (Phase A.3) treats normal/low identically (both fall through
    # to the same 30-day-engagement check), this toggle stopped changing
    # actual behavior the moment Phase A shipped. Confirmed dead in effect,
    # not just dead in theory, before removing.

    # ── Notification tuner check (legacy layer, overlap week — see T.3) ──
    # Still enforces by default (notify.legacy_limits=True) while its
    # decisions are logged against what the learned layer would have done,
    # so divergences are visible before this layer is retired for real.
    try:
        from app.services.notification_tuner import get_tuning_for_category
        from app.services.tunables import get_tunable_bool
        tuning_action = get_tuning_for_category(user_id, category)
        legacy_active = get_tunable_bool("notify.legacy_limits", True)
        if tuning_action in ("suppress", "double_cooldown"):
            await _log_limit_divergence(
                db, user_id, category, "notification_tuner", tuning_action, priority,
            )
        if legacy_active:
            if tuning_action == "suppress" and priority not in ("urgent", "critical"):
                logger.info(f"Notification suppressed by tuner: {category} | title={title[:60]}")
                return {"sent": False, "reason": "tuner_suppressed", "category": category}
            elif tuning_action == "double_cooldown":
                cooldown_hours = (cooldown_hours or _cooldown_for(category)) * 2
    except Exception:
        pass

    # ── Ban check: reject health/fitness/banned notifications before any delivery ──
    # _bypass_ban is reserved for explicit user-requested reports (e.g. the weekly
    # health debrief) where banned phrases like "calorie" are legitimate content,
    # not an unsolicited lecture from an autonomous worker.
    ban_reason = None if _bypass_ban else await _check_notification_ban(user_id, title, message, category, db)
    if ban_reason:
        logger.info(f"Notification banned at pipeline entry: {ban_reason} | title={title[:60]}")
        if db:
            await _log_notification(
                db, user_id, topic or f"{category}:{_hash_topic(title, message)}",
                category, title, message, priority, source, agent_run_id,
                0, sent=False, dedup_blocked=True,
            )
        return {"sent": False, "reason": "banned_topic", "ban_reason": ban_reason}

    # Phrasing stage (SARA_UNLEASHED Phase T.1): one voice, everywhere, before
    # anything is dedup-checked or delivered. Exempt categories (raw
    # timer/reminder fires) and any composer failure fall back to the
    # original text unchanged — see notification_composer.compose_notification_text.
    # _skip_phrasing is set only by route_through_attention_queue's internal
    # recursive calls, which already received composed text from this same
    # pass — without it every attention-routed push would compose twice.
    if not _skip_phrasing:
        try:
            from app.services.notification_composer import compose_notification_text
            composed = await compose_notification_text(title, message, category, source)
            title, message = composed["title"], composed["message"]
        except Exception as e:
            logger.debug(f"Phrasing stage skipped: {e}")

    # Route through attention queue when enabled (Phase 2 — Cortana Evolution)
    if not _bypass_attention and db:
        try:
            from app.core.config import settings
            if getattr(settings, 'autonomy_attention_enabled', False):
                return await route_through_attention_queue(
                    user_id=user_id, title=title, message=message,
                    priority=priority, category=category, source=source,
                    dedupe_key=topic, payload=payload, db=db,
                )
        except Exception as e:
            logger.debug(f"Attention queue routing failed, falling through: {e}")

    effective_cooldown = cooldown_hours if cooldown_hours is not None else _cooldown_for(category)
    effective_topic = topic or f"{category}:{_hash_topic(title, message)}"

    # Dedup check:
    # - normal path: category cooldown window
    # - fallback safety net: short exact-topic window even when category cooldown is 0
    if db and payload:
        grade = str(payload.get("prediction_grade") or "").lower()
        if grade == "confirmation":
            logger.info(
                f"Notification suppressed: prediction confirmation source={source} "
                f"category={category} title={title[:60]}"
            )
            return {"sent": False, "reason": "prediction_confirmation", "category": category}

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

    if db and payload:
        stimulus_key = payload.get("stimulus_key")
        generator = payload.get("generator") or source
        if stimulus_key:
            try:
                from app.services.habituation import note_delivery
                await note_delivery(db, generator, stimulus_key)
            except Exception as e:
                logger.debug(f"Habituation delivery note skipped: {e}")

    # Try desktop delivery via WebSocket first (real-time, no phone buzz).
    # Callers that have their own custom desktop fanout pass _bypass_desktop=True
    # to avoid a duplicate native SHOW_NOTIFICATION on top of their own UI.
    desktop_sent = False
    if not _bypass_desktop:
        try:
            from app.services.command_router import command_router, CommandMessage, CommandType
            from app.db.session import SessionLocal
            ws_db = SessionLocal()
            try:
                connected = command_router.get_connected_devices(user_id)
                if connected:
                    notif_payload = {"title": title, "message": message, "priority": priority, "source": source}
                    if overlay:
                        notif_payload["overlay"] = overlay
                    cmd = CommandMessage(
                        command_type=CommandType.SHOW_NOTIFICATION,
                        payload=notif_payload
                    )
                    desktop_sent = await command_router.send_command(ws_db, user_id, cmd)
                    if desktop_sent:
                        logger.info(f"Notification delivered via desktop WebSocket: {title[:50]}")
            finally:
                ws_db.close()
        except Exception as e:
            logger.debug(f"Desktop WebSocket delivery skipped: {e}")

    # ── Unified delivery policy (§3.6): sleep-gate the PUSH decision ──
    # Every push funnels through here — the escalation sweep, the attention-queue
    # buzz, and direct high-priority sends all reach this point. This is the one
    # chokepoint. If David is asleep and this isn't security/critical, HOLD it
    # for the morning digest instead of buzzing his phone at 5 AM (fixes N1).
    # Desktop delivery already happened above and is fine; only hold when the
    # item did NOT reach a connected desktop.
    if db and not desktop_sent:
        try:
            from app.services.delivery_policy import decide_delivery, hold_notification
            _decision = await decide_delivery(db, user_id, category, priority, source)
            if _decision.action == "hold":
                await hold_notification(
                    db, user_id=user_id, title=title, message=message,
                    category=category, priority=priority, source=source,
                    topic=effective_topic, payload=payload, decision=_decision,
                )
                await _log_notification(
                    db, user_id, effective_topic, category, title, message,
                    priority, source, agent_run_id, 0,
                    sent=False, dedup_blocked=False,
                    attention_item_id=_attention_item_id,
                )
                logger.info(
                    f"🌙 Push held (David asleep): {title[:50]!r} "
                    f"category={category} reason={_decision.reason}"
                )
                return {
                    "sent": False, "reason": "held_asleep", "held": True,
                    "deliver_after": _decision.deliver_after.isoformat()
                    if _decision.deliver_after else None,
                    "why_trace": _decision.why_trace,
                }
        except Exception as e:
            logger.debug(f"Delivery policy consult skipped: {e}")

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
        # Logged above (when db is available), so the unread count already
        # includes this notification. Without a db the push isn't logged and
        # won't show on the Notifications screen, so keep the legacy badge.
        unread_badge = await _get_unread_badge(db, user_id) if db else None
        push_success = await _send_push(
            tokens, title, message, priority, source,
            notification_id=notification_id,
            category=category,
            extra_data=extra_push_data,
            badge=unread_badge,
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

    # These notifications are logged after the push, so add them to the count.
    unread_badge = await _get_unread_badge(db, user_id) if db else None
    if unread_badge is not None:
        unread_badge += len(to_send)
    success = await _send_push(tokens, title, body, final_priority, source, category=category, badge=unread_badge)

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
    interruptibility = compute_interruptibility(activity=current_activity, user_id=user_id)
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

        # D: Jetson-present + high urgency + high interruptibility → also
        # speak a one-liner, capped 3/day. Desktop/push above already
        # covers the visual delivery; this adds voice on top when David is
        # near the Jetson and nothing richer (active desktop, phone chat)
        # is in use.
        if urgency_enum in (Urgency.URGENT, Urgency.IMPORTANT) and interruptibility.score >= 0.7:
            asyncio.ensure_future(_maybe_speak_via_jetson(user_id, title, message))

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


JETSON_SPEAK_DAILY_CAP = 3
JETSON_SPEAK_COUNT_KEY = "sara:jetson_speak_count:{user_id}:{date}"


async def _maybe_speak_via_jetson(user_id: str, title: str, message: str) -> None:
    """D: speak a proactive one-liner through the Jetson when it's the
    active surface (device_presence resolved "jetson" — desk presence +
    online, with no richer active desktop/phone-chat signal) and today's
    spoken-proactivity cap hasn't been hit."""
    try:
        from app.services.device_presence import resolve as resolve_presence
        from app.db.base import SessionLocal

        with SessionLocal() as sync_db:
            presence = await resolve_presence(sync_db, user_id)
        if presence.active_device_id != "jetson":
            return

        import redis.asyncio as aioredis
        from app.core.timezone import now as local_now

        redis_client = aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        key = JETSON_SPEAK_COUNT_KEY.format(user_id=user_id, date=local_now().date().isoformat())
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 90000)  # a little over 24h, clock-skew safe
        await redis_client.close()

        if count > JETSON_SPEAK_DAILY_CAP:
            logger.info(f"Jetson speak skipped — daily cap ({JETSON_SPEAK_DAILY_CAP}) reached")
            return

        from app.routes.sensory import speak_via_jetson
        spoken_text = f"{title}. {message}" if message and message != title else title
        await speak_via_jetson(spoken_text)
    except Exception as e:
        logger.debug(f"Jetson proactive speak skipped: {e}")


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
    interruptibility = compute_interruptibility(activity=current_activity, user_id=user_id)

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


async def _learned_buzz_decision(db: AsyncSession, user_id: str, category: str) -> bool:
    """Learned buzz decision (SARA_UNLEASHED Phase A.3). Replaces the blanket
    "normal/low priority never pushes, only high+ does" rule — that rule is
    exactly why proactive_checkins force-floored priority to `high` to be
    heard at all (R1-R3). The attention queue is now the single place "does
    this actually buzz the phone?" gets decided, and it learns: push a
    normal/low item iff this category's trailing 30-day engagement rate is
    >= 40% AND David is currently interruptible (>= 0.5). A category with
    fewer than 5 sends in the window has no track record yet and fails
    closed (inbox-only) until it earns a push."""
    try:
        row = await _db_execute(db, text("""
            SELECT count(*) FILTER (WHERE sent = true) AS sent,
                   count(*) FILTER (WHERE engaged = true) AS engaged
            FROM notification_log
            WHERE user_id = :uid AND category = :cat
              AND sent_at > NOW() - INTERVAL '30 days'
        """), {"uid": user_id, "cat": category})
        r = row.fetchone()
        sent, engaged = (int(r[0] or 0), int(r[1] or 0)) if r else (0, 0)
        if sent < 5 or (engaged / sent) < 0.4:
            return False
    except Exception as e:
        logger.debug(f"[buzz] engagement lookup failed for {category}: {e}")
        return False

    try:
        from app.services.activity_state_machine import activity_state_machine
        from app.services.interruptibility import compute_interruptibility
        score = compute_interruptibility(activity_state_machine.current).score
        return score >= 0.5
    except Exception as e:
        logger.debug(f"[buzz] interruptibility lookup failed: {e}")
        return False


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

    if payload and str(payload.get("prediction_grade") or "").lower() == "confirmation":
        logger.info(
            f"Attention item suppressed: prediction confirmation source={source} "
            f"category={category} title={title[:60]}"
        )
        return {"sent": False, "reason": "prediction_confirmation", "routed_through_attention": False}

    if not attention_enabled or not db:
        # Feature off — send directly (bypass attention to avoid recursion).
        # title/message already passed through the phrasing stage in the
        # caller (_send_notification_impl) — don't compose twice.
        return await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, topic=dedupe_key, category=category, source=source, db=db,
            _bypass_attention=True, _skip_phrasing=True, payload=payload,
        )

    # Time-based cooldown against recycled attention items. The DB unique
    # constraint on (user_id, dedupe_key) only blocks while status is
    # 'new'/'sent' — once the user reads or archives an item, the same
    # dedupe_key opens right back up, so a 15-min sweep (e.g. proactive
    # checkins) recreates a "new" item and re-broadcasts to the desktop
    # every cycle even though nothing new actually happened. Apply the same
    # per-category cooldown here that _check_dedup enforces on direct sends.
    if priority not in ("urgent", "critical"):
        effective_cooldown = _cooldown_for(category)
        if effective_cooldown > 0:
            recent = await _db_execute(db, text("""
                SELECT COUNT(*) FROM autonomy_attention_item
                WHERE user_id = :user_id AND category = :category
                  AND created_at > NOW() - MAKE_INTERVAL(secs => :cooldown_secs)
            """), {
                "user_id": user_id,
                "category": category,
                "cooldown_secs": effective_cooldown * 3600,
            })
            if (recent.scalar() or 0) > 0:
                logger.info(
                    f"Attention queue item suppressed by category cooldown: "
                    f"category={category} cooldown={effective_cooldown}h title={title[:60]}"
                )
                await _log_notification(
                    db, user_id, dedupe_key or f"{category}:{_hash_topic(title, message)}",
                    category, title, message, priority, source, None,
                    effective_cooldown, sent=False, dedup_blocked=True,
                )
                return {"sent": False, "reason": "attention_cooldown", "routed_through_attention": True}

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
            _bypass_attention=True, _skip_phrasing=True,
        )

    if payload:
        stimulus_key = payload.get("stimulus_key")
        generator = payload.get("generator") or source
        if stimulus_key:
            try:
                from app.services.habituation import note_delivery
                await note_delivery(db, generator, stimulus_key)
            except Exception as e:
                logger.debug(f"Habituation delivery note skipped: {e}")

    # High priority and above always pushes. Normal/low pushes too, iff the
    # learned buzz decision says this category has earned it right now
    # (Phase A.3) — otherwise it's inbox-only, same as before.
    should_push = priority in ("high", "urgent", "critical")
    if not should_push:
        should_push = await _learned_buzz_decision(db, user_id, category)

    if should_push:
        result = await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, topic=dedupe_key, category=category, source=source, db=db,
            _bypass_attention=True, _skip_phrasing=True, payload=payload,
            _attention_item_id=item_id,
        )
        result["attention_item_id"] = item_id
        result["routed_through_attention"] = True
        return result

    return {
        "sent": False,
        "attention_item_id": item_id,
        "routed_through_attention": True,
        "reason": "Low/normal priority routed to attention queue (buzz decision: inbox-only)",
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


def _chat_seed_text(title: str, message: str) -> str:
    """Build the substance of a notification for a chat prefill.

    Title is often just a generic bucket label (e.g. "Rhythm window opening",
    "Usual pattern coming up") while the actual specifics live in `message`.
    Dropping `message` is what produced prompts like "help me with your
    upcoming routine" that carry no real content.
    """
    title = (title or "").strip()
    message = (message or "").strip()
    if message and message.lower() != title.lower():
        return message
    return title


def _reply_prompt(title: str, message: str) -> str:
    """Prefill that quotes the notification's actual content and leaves room
    for the user to acknowledge, reinforce, or give a follow-up instruction —
    instead of a canned "help me with X" restating the generic title."""
    seed = _chat_seed_text(title, message)
    return f'Re: "{seed}"\n\n'


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
        actions.append({"id": "reply", "label": "Reply to Sara", "kind": "chat", "prompt": _reply_prompt(title, message)})
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
        actions.append({"id": "details", "label": "Details", "kind": "chat", "prompt": f"Tell me more about this security event: {_chat_seed_text(title, message)}"})
        has_chat = True
    elif category == "home":
        actions.append({"id": "ask_sara", "label": "Ask Sara", "kind": "chat", "prompt": _reply_prompt(title, message)})
        has_chat = True
    elif category in ("health", "fitness", "wellness"):
        actions.append({"id": "discuss", "label": "Discuss", "kind": "chat", "prompt": _reply_prompt(title, message)})
        actions.append({"id": "remind_later", "label": "Remind me later", "kind": "add_reminder", "default_minutes": 120})
        has_chat = True
    elif category == "weather":
        actions.append({"id": "remind_me", "label": "Remind me", "kind": "add_reminder", "default_minutes": 60})
    elif category == "deferred_action":
        actions.append({"id": "do_now", "label": "Do now", "kind": "chat", "prompt": f"Let's do this now: {_chat_seed_text(title, message)}"})
        actions.append({"id": "snooze_1h", "label": "Snooze 1h", "kind": "snooze", "minutes": 60})
        actions.append({"id": "set_reminder", "label": "Set reminder", "kind": "add_reminder", "default_minutes": 60})
        has_chat = True
    else:
        # general / unknown
        actions.append({"id": "discuss", "label": "Discuss", "kind": "chat", "prompt": _reply_prompt(title, message)})
        actions.append({"id": "remind_me", "label": "Remind me", "kind": "add_reminder", "default_minutes": 60})
        has_chat = True

    # Universal tail: Ask Sara (if no chat action yet) + Done
    if not has_chat:
        actions.append({"id": "ask_sara", "label": "Ask Sara", "kind": "chat", "prompt": _reply_prompt(title, message)})
    actions.append({"id": "done", "label": "Done", "kind": "complete"})

    # SARA_UNLEASHED Phase T.4: the triad every proactive item gets, on top
    # of whatever category-specific actions above already serve as "do it".
    # "Not now" re-surfaces THIS item at the next context change instead of
    # spawning a duplicate or a fixed-timer snooze. "Stop these" is the
    # correction channel that used to only exist in the Sunday digest —
    # available at the moment of annoyance instead of a week later.
    actions.append({"id": "not_now", "label": "Not now", "kind": "not_now"})
    actions.append({"id": "stop_these", "label": "Stop these", "kind": "stop_these"})

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


_CATEGORY_LIMIT_CATEGORIES = (
    "home", "security", "checkin", "weather", "health", "fitness", "wellness", "acs_discovery",
)


async def _log_limit_divergence(
    db: Optional[AsyncSession], user_id: str, category: str, source: str, old_action: str, priority: str,
) -> None:
    """SARA_UNLEASHED Phase T.3 overlap-week safety check. Every time a legacy
    suppression layer (notification_tuner or the category-limit dict) would
    act, also read what the learned layer (30-day engagement, same signal
    _learned_buzz_decision uses) currently says for this category, and log
    both side by side as `limit_divergence`. This is the record a future
    session reviews before flipping `notify.legacy_limits` off for good —
    the log line format is deliberately grep-friendly (`grep limit_divergence`)."""
    if db is None:
        return
    try:
        would_push = await _learned_buzz_decision(db, user_id, category)
        logger.warning(
            f"limit_divergence: source={source} category={category} "
            f"old_action={old_action} priority={priority} learned_layer_would_push={would_push}"
        )
    except Exception as e:
        logger.debug(f"limit_divergence logging failed: {e}")


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

    # Category-level rate limit: prevent LLM from varying topic names for the same issue.
    # SARA_UNLEASHED Phase T.3: values now live in tunable_setting (migration 094)
    # instead of a Python literal — same defaults, but inspectable/editable like
    # every other tunable, and the natural seed for the learned layer that's meant
    # to eventually absorb this responsibility (attention_policy.surface_budget).
    category = topic.split(":")[0] if ":" in topic else topic
    if include_category_limits and category in _CATEGORY_LIMIT_CATEGORIES:
        from app.services.tunables import get_tunable_int, get_tunable_float, get_tunable_bool
        max_count = get_tunable_int(f"notify.category_limit.{category}.max_count", 3)
        window_hours = get_tunable_float(f"notify.category_limit.{category}.window_hours", 6.0)
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
            legacy_active = get_tunable_bool("notify.legacy_limits", True)
            await _log_limit_divergence(db, user_id, category, "category_limit", "block", "n/a")
            if legacy_active:
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
    """Log a notification attempt to notification_log.

    Dedup-blocked attempts (Phase A.4) don't insert a fresh churn row — they
    increment `blocked_count` on the most recent blocked row for this exact
    topic instead. This is what killed the 106/week of pure log churn from
    repeated dedup-blocked sends (SARA_UNLEASHED R3)."""
    if dedup_blocked:
        bumped = await _db_execute(db, text("""
            UPDATE notification_log
            SET blocked_count = COALESCE(blocked_count, 1) + 1
            WHERE id = (
                SELECT id FROM notification_log
                WHERE user_id = :user_id AND topic = :topic AND dedup_blocked = TRUE
                ORDER BY created_at DESC LIMIT 1
            )
            RETURNING id
        """), {"user_id": user_id, "topic": topic})
        row = bumped.fetchone()
        if row:
            return row[0]
        # First block for this topic since the last real send — fall through
        # to insert a single row that future blocks will increment.

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
    notification_log_id = row[0] if row else None

    if sent and notification_log_id:
        await _record_ml_notification_features(db, user_id, str(notification_log_id), category)

    return notification_log_id


async def _record_ml_notification_features(db: AsyncSession, user_id: str, notification_log_id: str, category: str) -> None:
    """Capture features-at-send-time for ml_notification_outcome (C1/C3).
    The `outcome`/`outcome_latency_seconds` columns start NULL and are
    back-filled later by app.tasks.ml.sync_notification_outcomes once the
    user has opened/dismissed/ignored it — notification_log's own
    engaged/dismissed_at/read_at columns are the source of truth for that."""
    try:
        from app.services.activity_state_machine import activity_state_machine
        from app.services.interruptibility import compute_interruptibility
        from zoneinfo import ZoneInfo
        import uuid as _uuid

        now = datetime.now(ZoneInfo("America/New_York"))
        current_activity = activity_state_machine.current
        interruptibility = compute_interruptibility(activity=current_activity, user_id=user_id)

        # C3: notification_value shadow prediction — same features, framed as
        # "will this specific send be engaged with" rather than "is now a
        # good moment in general." Shares the same label source
        # (ml_notification_outcome) as interruptibility_v2.
        try:
            from app.services.ml import inference as ml_inference
            ml_inference.predict(
                "notification_value",
                {
                    "hour": now.hour,
                    "day_of_week": now.weekday(),
                    "activity_state": current_activity.state.value,
                    "device": "unknown",
                    "category": category,
                    "interruptibility_score": interruptibility.score,
                },
                user_id=user_id,
                mode="shadow",
            )
        except Exception as e:
            logger.debug(f"notification_value shadow prediction skipped: {e}")

        await _db_execute(db, text("""
            INSERT INTO ml_notification_outcome
            (id, user_id, notification_log_id, sent_at, hour, day_of_week,
             activity_state, interruptibility_score, category, features)
            VALUES
            (:id, :user_id, :notification_log_id, NOW(), :hour, :day_of_week,
             :activity_state, :interruptibility_score, :category, CAST(:features AS jsonb))
        """), {
            "id": str(_uuid.uuid4()),
            "user_id": user_id,
            "notification_log_id": notification_log_id,
            "hour": now.hour,
            "day_of_week": now.weekday(),
            "activity_state": current_activity.state.value,
            "interruptibility_score": interruptibility.score,
            "category": category,
            "features": json.dumps({
                "hour": now.hour,
                "day_of_week": now.weekday(),
                "activity_state": current_activity.state.value,
                "interruptibility_score": interruptibility.score,
                "category": category,
                "device": "unknown",
            }),
        })
    except Exception as e:
        logger.debug(f"ml_notification_outcome capture skipped: {e}")


async def _get_unread_badge(db: AsyncSession, user_id: str) -> Optional[int]:
    """App icon badge for pushes — same formula as the assistant-inbox badge
    (unread attention + clarifications + unread unlinked notifications) so the
    icon, tab badge, and inbox screen always agree."""
    try:
        from app.routes.assistant_inbox import BADGE_SQL
        result = await _db_execute(db, text(BADGE_SQL), {"user_id": user_id})
        row = result.fetchone()
        return int(row[0]) if row else None
    except Exception as e:
        logger.debug(f"Unread badge count failed: {e}")
        return None


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


# Categories that are FYI/ambient — deliver quietly (no screen wake).
_PASSIVE_CATEGORIES = {"acs_discovery", "learning_review", "inbox_digest", "attention_digest"}
# Categories where a miss is genuinely time-critical — break through Focus.
_TIME_SENSITIVE_CATEGORIES = {"security", "calendar_prep", "health_alert", "timer"}


def _interruption_level(priority: str, category: str) -> str:
    """Map delivery-policy priority/category → iOS interruption level (§5.4.1).

    passive | active | timeSensitive | critical.
    """
    cat = (category or "").lower()
    prio = (priority or "").lower()
    if prio == "critical" or cat == "security":
        return "critical" if prio == "critical" else "timeSensitive"
    if cat in _TIME_SENSITIVE_CATEGORIES or prio == "urgent":
        return "timeSensitive"
    if cat in _PASSIVE_CATEGORIES or prio in ("low", "silent"):
        return "passive"
    return "active"


async def _send_push(
    tokens: List[str],
    title: str,
    body: str,
    priority: str = "normal",
    source: str = "unified_heartbeat",
    notification_id: Optional[int] = None,
    category: str = "general",
    extra_data: Optional[Dict[str, Any]] = None,
    badge: Optional[int] = None,
) -> bool:
    """Send mobile push notification to all of the user's device tokens."""
    unique_tokens = [t for t in dict.fromkeys(tokens) if t]
    if not unique_tokens:
        return False

    normalized_priority = _normalize_priority(priority)
    push_priority = "high" if normalized_priority in ("high", "urgent", "critical") else "default"
    push_data: Dict[str, Any] = {
        "type": "heartbeat" if source == "unified_heartbeat" else source,
        "priority": normalized_priority,
        "title": title,
        "message": body,
        "category": category,
    }
    if notification_id is not None:
        push_data["notification_id"] = notification_id
    if extra_data:
        # extra_data wins over the defaults above so callers can override, e.g.,
        # set their own type or attach note_id / route hints for the iOS handler.
        push_data.update(extra_data)

    # Deep-link target for tap / long-press routing on the client. Callers may
    # set data.target (+ data.params) explicitly via extra_data; otherwise derive
    # a sensible default from the category so EVERY notification opens somewhere
    # relevant instead of falling back to a generic inbox.
    if "target" not in push_data:
        _target_map = {
            "email": "email", "chat_response": "chat", "message": "chat",
            "checkin": "chat", "check_in": "chat", "thread_followup": "chat",
            "agent_task": "agent_tasks", "background_task": "agent_tasks", "research": "agent_tasks",
            "agent_clarification": "chat",
            "calendar": "calendar", "calendar_prep": "calendar", "schedule": "calendar",
            "reminder": "inbox", "timer_complete": "inbox", "inbox_digest": "inbox",
            "wellness": "fitness", "health": "fitness", "weekly_health_report": "fitness",
            "recovery": "fitness", "fitness": "fitness",
            "security": "system", "home": "system",
            "acs_discovery": "acs", "acs_request": "acs", "acs_daemon": "acs",
            "learning_review": "learn",
        }
        c = (category or "").lower()
        s = (source or "").lower()
        if c in _target_map:
            push_data["target"] = _target_map[c]
        elif any(k in s for k in ("deliberation", "subconscious", "system", "promotion")):
            push_data["target"] = "system"
        else:
            push_data["target"] = "inbox"

    # Map category to interactive notification category id
    push_category_map = {
        "checkin": "MORNING_CHECKIN",
        "acs_discovery": "ACS_DISCOVERY",
        "calendar_prep": "SARA_INSIGHT",
        "system_health": "GENERAL_NUDGE",
        # §5.4: answerable categories (registered on-device — need a rebuild wave).
        "automation": "SARA_SUGGESTION",       # belief-promotion "want me to automate this?"
        "pattern_suggestion": "SARA_SUGGESTION",
        "thread_followup": "THREAD_FOLLOWUP",
    }
    push_category_id = push_category_map.get(category, "GENERAL_NUDGE")

    # §5.4.1: iOS interruption level gives the delivery policy native teeth on the
    # device. This is a runtime push field — it takes effect on the CURRENT build
    # (no rebuild needed). passive = no screen wake (FYI); timeSensitive = breaks
    # Focus (prep-imminent, security, acute health); critical needs the Critical
    # Alerts entitlement + opt-in (iOS silently downgrades it otherwise, so it's
    # safe to send).
    interruption_level = _interruption_level(normalized_priority, category)

    messages = [
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": push_data,
            "priority": push_priority,
            "categoryId": push_category_id,
            "interruptionLevel": interruption_level,
            "_contentAvailable": True,
            # Real unread count when the caller could compute it; the app icon
            # badge then matches the Notifications screen instead of a stuck "1".
            "badge": badge if badge is not None else 1,
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
