"""Conversation-pattern triggers.

Reads `conversation_turn` to catch behaviors like the 3am chat session.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.narrator.triggers.base import (
    Trigger,
    TriggerContext,
    register_trigger,
)

logger = logging.getLogger(__name__)


MIDNIGHT_ORACLE_HOURS = (2, 3, 4)  # 2am, 3am, 4am ET
MIDNIGHT_ORACLE_MIN_MESSAGES = 3


@register_trigger("midnight_oracle", cooldown_seconds=20 * 60 * 60)
class MidnightOracleTrigger(Trigger):
    """3+ user messages to Sara between 2-5am in the last 24h.

    Quiet observation. The persona has tact about late nights — it does not
    moralize, it just notes that someone was awake when they shouldn't have
    been, asking questions of an AI.

    `conversation_turn.created_at` is naive timestamp; we treat it as ET per
    project convention.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) AS n,
                           MIN(created_at) AS first_at,
                           MAX(created_at) AS last_at
                    FROM conversation_turn
                    WHERE user_id = :uid
                      AND role = 'user'
                      AND created_at > NOW() - INTERVAL '24 hours'
                      AND EXTRACT(HOUR FROM created_at) = ANY(:hours)
                    """
                ),
                {
                    "uid": user_id,
                    "hours": list(MIDNIGHT_ORACLE_HOURS),
                },
            )
        ).mappings().first()

        if not row or int(row["n"] or 0) < MIDNIGHT_ORACLE_MIN_MESSAGES:
            return None

        facts = {
            "message_count": int(row["n"]),
            "first_at": row["first_at"].isoformat() if row["first_at"] else None,
            "last_at": row["last_at"].isoformat() if row["last_at"] else None,
            "hours_window": "2-5am",
        }
        summary = (
            f"{facts['message_count']} messages to Sara between 2 and 5 AM "
            "in the last 24 hours"
        )
        return TriggerContext(
            trigger_name="midnight_oracle",
            severity="observation",
            facts=facts,
            summary=summary,
            # One fire per date-bucket; if it happens again tomorrow, refire.
            dedup_key=f"midnight_oracle:{row['last_at'].date().isoformat() if row['last_at'] else 'unknown'}",
        )
