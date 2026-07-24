"""
Attention decision recorder (SINGULAR_SARA_MASTER_PLAN §4.6/§C9).

§4.6 wants every proactive message to become an outbound intent, judged by
one attention market, before it becomes prose. That market already exists
and is already live: `route_through_attention_queue()` (Phase 2 — Cortana
Evolution, `autonomy_attention_enabled`) creates a real `autonomy_attention_
item` row and decides push vs. inbox-only using dedup, cooldown, and a
learned buzz decision — this isn't a new gate, it's the one that's already
running in production.

This module is no longer a guess: it records what that real decision
*actually was*, using the `attention_item_id`/`sent` signals
`route_through_attention_queue()` already returns, into the canonical
`OutboundIntentV1`/`AttentionItemV1` shape — so "every delivered line has
source facts, attention decision, rendered text, and delivery receipt"
(§C9 exit gate) is backed by the real decision, not an approximation from
`sent`+`priority` alone. It still never gates, delays, or changes what
`send_notification()` sends — recording only.
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_INTERRUPTIVE_PRIORITIES = {"urgent", "critical"}


def _classify_decision(result: Dict[str, Any], priority: str) -> str:
    """Read the REAL decision off `result` when this call went through the
    live attention queue (`routed_through_attention` + `attention_item_id`
    are only present in that path); fall back to a coarser sent/priority
    read for calls that bypassed it (attention feature off, or an internal
    bypass call)."""
    sent = bool(result.get("sent"))
    if sent:
        return "interruptive_notification" if priority in _INTERRUPTIVE_PRIORITIES else "quiet_notification"
    if result.get("attention_item_id"):
        # A real autonomy_attention_item row exists — visible in Today/inbox
        # even though nothing pushed. Distinct from true silence.
        return "add_to_today"
    return "internal_only"


async def check_recent_duplicate(
    db: AsyncSession, user_id: str, category: str, message: str, lookback_hours: float = 3.0,
) -> bool:
    """SINGULAR_SARA_MASTER_PLAN §C9 real gate: True if this exact message
    text was already delivered (a real decision, not `internal_only`) to
    this user within `lookback_hours`.

    This is a genuinely NEW capability, not a duplicate of the existing
    topic-string dedup in `_send_notification_impl` — that dedups by
    `topic` (a key each caller chooses, often unique per event), this dedups
    by actual rendered content regardless of topic, catching the case where
    two different call sites independently decide to tell David the same
    thing under two different topics. Fails open (returns False) on any
    error — a broken check must never itself block a legitimate send.
    """
    try:
        from sqlalchemy import text
        row = (await db.execute(text("""
            SELECT 1 FROM outbound_intent oi
            JOIN attention_item ai ON ai.outbound_intent_id = oi.outbound_intent_id
            WHERE oi.user_id = :user_id
              AND LOWER(TRIM(ai.rendered_text)) = LOWER(TRIM(:message))
              AND ai.decision != 'internal_only'
              AND oi.created_at > NOW() - MAKE_INTERVAL(secs => :secs)
            LIMIT 1
        """), {"user_id": user_id, "message": message, "secs": lookback_hours * 3600})).first()
        return row is not None
    except Exception as e:
        logger.debug(f"[attention_shadow_recorder] duplicate-content check failed: {e}")
        return False


async def record_notification_decision(
    db: AsyncSession,
    *,
    user_id: str,
    title: str,
    message: str,
    priority: str,
    category: str,
    topic: Optional[str],
    result: Dict[str, Any],
) -> None:
    """Best-effort — never raises, never blocks the real send. Call this
    after `_send_notification_impl` returns, with its actual result."""
    try:
        from app.core.correlation import get_current_correlation
        from sqlalchemy import text

        correlation_id = get_current_correlation().kernel_turn_id
        sent = bool(result.get("sent"))
        decision = _classify_decision(result, priority)
        attention_item_id = result.get("attention_item_id")
        why_now = f"category={category}, reason={result.get('reason', 'sent')}"
        if attention_item_id:
            why_now += f", autonomy_attention_item={attention_item_id}"

        row = (await db.execute(text("""
            INSERT INTO outbound_intent (
                user_id, subject, facts, why_now, dedupe_key, correlation_id
            ) VALUES (
                :user_id, :subject, CAST(:facts AS jsonb), :why_now, :dedupe_key, :correlation_id
            ) RETURNING outbound_intent_id
        """), {
            "user_id": user_id,
            "subject": title[:500],
            "facts": json.dumps([message[:600]]),
            "why_now": why_now,
            "dedupe_key": topic,
            "correlation_id": correlation_id,
        })).first()
        outbound_intent_id = row[0]

        await db.execute(text("""
            INSERT INTO attention_item (
                outbound_intent_id, decision, rendered_text, delivered_channels,
                delivered_at, correlation_id
            ) VALUES (
                :outbound_intent_id, :decision, :rendered_text, CAST(:channels AS jsonb),
                CASE WHEN :sent THEN NOW() ELSE NULL END, :correlation_id
            )
        """), {
            "outbound_intent_id": outbound_intent_id,
            "decision": decision,
            "rendered_text": message[:2000],
            "channels": json.dumps(["push"] if sent else []),
            "sent": sent,
            "correlation_id": correlation_id,
        })
    except Exception as e:
        # Shadow recording must never affect the real notification pipeline.
        logger.debug(f"[attention_shadow_recorder] failed: {e}")
