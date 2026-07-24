"""
Attention shadow recorder (SINGULAR_SARA_MASTER_PLAN §4.6/§C9).

§4.6 wants every proactive message to become an outbound intent, judged by
one attention market, before it becomes prose. `send_notification()` already
makes that judgment on every call — dedup, cooldown, ban, tuner suppression,
priority — it just doesn't write it down as one canonical decision record.

This module shadow-records that decision after the fact: it does not gate,
delay, or change what `send_notification()` actually sends. It maps the
real `{sent, reason, priority, ...}` result the pipeline already produced
into one `OutboundIntentV1` + `AttentionItemV1` pair and persists them, so
"every delivered line has source facts, attention decision, rendered text,
and delivery receipt" (§C9 exit gate) becomes something you can query today,
ahead of the real attention market that will eventually make these decisions
instead of just describing them.
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Real send_notification() failure/skip reasons that mean "nothing reached
# David" — mapped to internal_only. Anything not in this set but sent=False
# still maps to internal_only (fail toward the conservative bucket).
_SILENT_REASONS = {
    "tuner_suppressed", "banned_topic", "prediction_confirmation", "dedup",
    "no_tokens", "push_failed", "all_deduped", "attention_cooldown", "empty_queue",
}

_INTERRUPTIVE_PRIORITIES = {"urgent", "critical"}


def _classify_decision(sent: bool, priority: str) -> str:
    if not sent:
        return "internal_only"
    if priority in _INTERRUPTIVE_PRIORITIES:
        return "interruptive_notification"
    return "quiet_notification"


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
        decision = _classify_decision(sent, priority)

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
            "why_now": f"category={category}, reason={result.get('reason', 'sent')}",
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
