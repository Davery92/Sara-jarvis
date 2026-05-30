"""Fitness/recovery-domain triggers.

Reads `external_workout` (Apple Health imports) and `daily_recovery_log`
(David's nightly sleep + soreness log). All times in the user's local
timezone via app.core.timezone — workout streaks are by *calendar day*,
not 24h windows.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today as et_today
from app.services.narrator.triggers.base import (
    Trigger,
    TriggerContext,
    register_trigger,
)

logger = logging.getLogger(__name__)


# Tiered milestone thresholds. Hitting any of these in order is a moment.
GYM_STREAK_MILESTONES = (7, 14, 30, 60, 100)

# Minimum prior streak length before "the streak broke" is narratively
# meaningful. Below this, a missed day isn't a story.
GYM_STREAK_BREAK_MIN = 7

# How many of the last N nights must be below the sleep threshold before
# "sleep debt compounds" fires.
SLEEP_DEBT_LOOKBACK_NIGHTS = 5
SLEEP_DEBT_MIN_LOW_NIGHTS = 3
SLEEP_DEBT_HOURS_THRESHOLD = 6.0


async def _workout_days(
    db: AsyncSession, user_id: str, days_back: int
) -> set[date]:
    """Return the set of local-date days in the lookback window on which
    David logged at least one workout."""
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT (started_at AT TIME ZONE 'America/New_York')::date AS day
                FROM external_workout
                WHERE user_id = :uid
                  AND started_at > NOW() - make_interval(days => :days)
                """
            ),
            {"uid": user_id, "days": days_back},
        )
    ).mappings().all()
    return {r["day"] for r in rows}


def _current_streak(workout_days: set[date], end: date) -> int:
    """Length of the consecutive-workout streak ending on `end` (inclusive).
    Returns 0 if `end` itself has no workout."""
    if end not in workout_days:
        return 0
    streak = 0
    d = end
    while d in workout_days:
        streak += 1
        d -= timedelta(days=1)
    return streak


@register_trigger("gym_streak_milestone", cooldown_seconds=23 * 60 * 60)
class GymStreakMilestoneTrigger(Trigger):
    """A workout streak just crossed a milestone (7/14/30/60/100 days).

    Severity scales: 7-day grants grudging respect, 30+ shifts toward
    deflected (real acknowledgment, undercut at the end). Cooldown is per
    milestone — the same threshold can only fire once.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        today = et_today()
        days = await _workout_days(db, user_id, days_back=120)
        streak = _current_streak(days, today)
        # Also check yesterday in case today's workout hasn't synced yet.
        if streak == 0:
            streak = _current_streak(days, today - timedelta(days=1))
        if streak < GYM_STREAK_MILESTONES[0]:
            return None

        # Highest milestone reached so far.
        crossed = max(m for m in GYM_STREAK_MILESTONES if m <= streak)

        # Only narrate within ~36h of crossing. After that, the moment passed.
        # If the streak is well past the milestone, dedup keeps us quiet.
        facts = {
            "streak_length": streak,
            "milestone_crossed": crossed,
        }
        # The longer the streak, the closer to deflected (real) praise.
        severity = "deflected" if crossed >= 30 else "grudging"
        summary = f"Workout streak: {streak} days; just crossed {crossed}."
        return TriggerContext(
            trigger_name="gym_streak_milestone",
            severity=severity,
            facts=facts,
            summary=summary,
            # One fire per milestone tier. 7-day streak fires once at 7,
            # never refires until streak hits 14.
            dedup_key=f"gym_streak_milestone:{crossed}",
        )


@register_trigger("gym_streak_broken", cooldown_seconds=24 * 60 * 60)
class GymStreakBrokenTrigger(Trigger):
    """A meaningful workout streak just ended.

    Quiet observation — not a roast. The body doesn't owe the System
    anything, and pretending otherwise is the kind of coach-voice the
    persona refuses.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        today = et_today()
        days = await _workout_days(db, user_id, days_back=180)

        # If David worked out today, the streak isn't broken.
        if today in days:
            return None
        # If yesterday wasn't a workout either, the streak ended earlier; the
        # narrative beat is already stale.
        yesterday = today - timedelta(days=1)
        day_before = today - timedelta(days=2)
        if yesterday in days and day_before not in days:
            # Only one day of workout — not a streak.
            return None

        # Find the streak that ended at `yesterday` (workout) followed by today
        # (no workout). If yesterday wasn't a workout, this trigger doesn't
        # fire — the streak already broke before today.
        if yesterday not in days:
            return None
        prior_streak = _current_streak(days, yesterday)
        if prior_streak < GYM_STREAK_BREAK_MIN:
            return None

        facts = {
            "prior_streak_length": prior_streak,
            "broken_on": today.isoformat(),
        }
        summary = (
            f"Workout streak of {prior_streak} days ended; no workout today."
        )
        return TriggerContext(
            trigger_name="gym_streak_broken",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"gym_streak_broken:{today.isoformat()}",
        )


@register_trigger("sleep_debt_compounds", cooldown_seconds=2 * 24 * 60 * 60)
class SleepDebtCompoundsTrigger(Trigger):
    """≥3 of the last 5 nights below ~6 hours of sleep.

    Quiet observation — sleep is not a thing to roast about. The persona
    notes the pattern; David decides whether to do anything.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT log_date, sleep_hours
                    FROM daily_recovery_log
                    WHERE user_id = :uid
                      AND sleep_hours IS NOT NULL
                      AND log_date > (CURRENT_DATE - make_interval(days => :n))
                    ORDER BY log_date DESC
                    LIMIT :n
                    """
                ),
                {
                    "uid": user_id,
                    "n": SLEEP_DEBT_LOOKBACK_NIGHTS,
                },
            )
        ).mappings().all()

        if len(rows) < SLEEP_DEBT_MIN_LOW_NIGHTS:
            return None

        low_nights = [
            r for r in rows
            if float(r["sleep_hours"]) < SLEEP_DEBT_HOURS_THRESHOLD
        ]
        if len(low_nights) < SLEEP_DEBT_MIN_LOW_NIGHTS:
            return None

        recent_hours = [float(r["sleep_hours"]) for r in rows]
        avg = sum(recent_hours) / len(recent_hours)

        facts = {
            "low_nights_count": len(low_nights),
            "lookback_nights": SLEEP_DEBT_LOOKBACK_NIGHTS,
            "threshold_hours": SLEEP_DEBT_HOURS_THRESHOLD,
            "avg_hours": round(avg, 1),
            "recent_hours": recent_hours,
        }
        summary = (
            f"{len(low_nights)} of the last {len(rows)} nights below "
            f"{SLEEP_DEBT_HOURS_THRESHOLD}h sleep; "
            f"average {facts['avg_hours']}h"
        )
        return TriggerContext(
            trigger_name="sleep_debt_compounds",
            severity="observation",
            facts=facts,
            summary=summary,
            # Refires when the count climbs (4-of-5, 5-of-5).
            dedup_key=f"sleep_debt:{len(low_nights)}_of_{len(rows)}",
        )
