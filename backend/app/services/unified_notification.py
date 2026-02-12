"""
Unified Notification Pipeline

Single entry point for all notifications with topic-based deduplication.
Replaces scattered Expo push implementations across heartbeat, subconscious,
proactive, and anticipation services.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default user ID
DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Default cooldowns by category (hours)
DEFAULT_COOLDOWNS = {
    "calendar": 24.0,
    "weather": 8.0,
    "checkin": 4.0,
    "email": 4.0,
    "security": 0.0,
    "home": 2.0,
    "reminder": 0.0,
    "timer": 0.0,
    "general": 4.0,
}


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
        priority: "low", "normal", or "high"
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

    effective_cooldown = cooldown_hours if cooldown_hours is not None else DEFAULT_COOLDOWNS.get(category, 4.0)
    effective_topic = topic or f"{category}:{_hash_topic(title, message)}"

    # Dedup check if we have a db session and a cooldown window
    if db and effective_cooldown > 0:
        is_dup = await _check_dedup(db, user_id, effective_topic, effective_cooldown)
        if is_dup:
            logger.info(f"Notification dedup blocked: topic={effective_topic} cooldown={effective_cooldown}h")
            # Log the blocked attempt
            await _log_notification(
                db, user_id, effective_topic, category, title, message,
                priority, source, agent_run_id, effective_cooldown,
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

    # Send via Expo push only if desktop delivery failed or wasn't available
    success = desktop_sent
    if tokens and not desktop_sent:
        expo_success = await _send_expo_push(tokens, title, message, priority, source)
        success = success or expo_success

    if not success:
        return {"sent": False, "reason": "expo_failed"}

    # Log successful send
    if db:
        notification_id = await _log_notification(
            db, user_id, effective_topic, category, title, message,
            priority, source, agent_run_id, effective_cooldown,
            sent=True, dedup_blocked=False,
            attention_item_id=_attention_item_id,
        )
    else:
        notification_id = None

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

    # Filter through dedup
    to_send = []
    results = []
    for notif in notifications:
        topic = notif.get("topic") or f"{notif.get('category', 'general')}:{_hash_topic(notif['title'], notif['message'])}"
        category = notif.get("category", "general")
        cooldown = notif.get("cooldown_hours") or DEFAULT_COOLDOWNS.get(category, 4.0)

        if db and cooldown and cooldown > 0:
            is_dup = await _check_dedup(db, user_id, topic, cooldown)
            if is_dup:
                await _log_notification(
                    db, user_id, topic, category, notif["title"], notif["message"],
                    notif.get("priority", "normal"), source, agent_run_id, cooldown,
                    sent=False, dedup_blocked=True
                )
                results.append({"topic": topic, "sent": False, "reason": "dedup"})
                continue

        to_send.append({**notif, "topic": topic, "category": category, "cooldown": cooldown})

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
        final_priority = "high" if any(n.get("priority") == "high" for n in to_send) else "normal"

    # Send
    tokens = await _get_push_tokens(db, user_id) if db else await _get_push_tokens_sync(user_id)
    if not tokens:
        return {"sent": False, "reason": "no_tokens"}

    success = await _send_expo_push(tokens, title, body, final_priority, source)

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
    Priority high/urgent/critical → create item AND send push.

    Behind AUTONOMY_ATTENTION_ENABLED flag — when off, sends directly.
    """
    try:
        from app.core.config import settings
        attention_enabled = getattr(settings, 'autonomy_attention_enabled', False)
    except Exception:
        attention_enabled = False

    if not attention_enabled or not db:
        # Feature off — send directly (bypass attention to avoid recursion)
        return await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, category=category, source=source, db=db,
            _bypass_attention=True,
        )

    from app.services.autonomy.attention_queue import attention_queue

    # Always create attention item
    item_id = await attention_queue.create_item(
        db=db, user_id=user_id, title=title, body=message,
        category=category, priority=priority, source=source,
        dedupe_key=dedupe_key, payload=payload,
    )

    # High priority and above: also send push (bypass attention to avoid recursion)
    if priority in ("high", "urgent", "critical"):
        result = await send_notification(
            user_id=user_id, title=title, message=message,
            priority=priority, category=category, source=source, db=db,
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
    result = await db.execute(text("""
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


async def _check_dedup(
    db: AsyncSession,
    user_id: str,
    topic: str,
    cooldown_hours: float,
) -> bool:
    """Check if a notification with this topic OR same category was sent within the cooldown window."""
    # Exact topic match check
    result = await db.execute(text("""
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
        "home": (3, 6.0),      # max 3 per 6 hours
        "security": (4, 6.0),  # max 4 per 6 hours
        "checkin": (1, 6.0),   # max 1 per 6 hours
        "weather": (2, 8.0),   # max 2 per 8 hours
    }
    if category in category_limits:
        max_count, window_hours = category_limits[category]
        result = await db.execute(text("""
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
    result = await db.execute(text("""
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
    result = await db.execute(text("""
        SELECT token FROM push_token
        WHERE user_id = :user_id AND is_active = true
    """), {"user_id": user_id})
    return [r.token for r in result.fetchall()]


async def _get_push_tokens_sync(user_id: str) -> List[str]:
    """Fallback: get push tokens with a sync engine."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings

    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        result = db.execute(text("""
            SELECT token FROM push_token
            WHERE user_id = :user_id AND is_active = true
        """), {"user_id": user_id}).fetchall()
        return [r.token for r in result]
    finally:
        db.close()


async def _send_expo_push(
    tokens: List[str],
    title: str,
    body: str,
    priority: str = "normal",
    source: str = "unified_heartbeat",
) -> bool:
    """Send push notification via Expo Push API."""
    if not tokens:
        return False

    expo_priority = "high" if priority == "high" else "default"
    messages = [
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": {
                "type": "heartbeat" if source == "unified_heartbeat" else source,
                "priority": priority,
                "title": title,
                "message": body,
            },
            "priority": expo_priority,
        }
        for token in tokens
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
                logger.info(f"Expo push sent: {title[:50]}")
                return True
            else:
                logger.error(f"Expo push failed: {response.status_code} - {response.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Expo push error: {e}")
        return False
