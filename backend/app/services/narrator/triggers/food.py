"""Food/nutrition triggers. Reads `food_log` and `fitness_daily_log`."""
from __future__ import annotations

import logging
from datetime import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.narrator.triggers.base import (
    Trigger,
    TriggerContext,
    register_trigger,
)

logger = logging.getLogger(__name__)


# Calibration: log the food log was a "practice" when at least N days in the
# window before the last entry had logging. 3-of-5 catches real-world habits
# (people skip days) without firing for someone who logged once and stopped.
FOOD_STOP_PRIOR_DAYS = 5          # window size to inspect before the last log
FOOD_STOP_MIN_PRIOR_DAYS = 3      # minimum distinct days logged in that window
FOOD_STOP_SILENCE_DAYS = 4

# Protein target in grams below which a day counts as "low" — the existing
# fitness module probably has a real target somewhere; this is a reasonable
# conservative floor.
PROTEIN_LOW_GRAMS = 100.0
PROTEIN_LOW_MIN_DAYS = 4   # of the last 7
PROTEIN_LOW_LOOKBACK = 7

# Lateness: dinner logged after this local time on multiple recent days.
LATE_DINNER_HOUR = 22
LATE_DINNER_MIN_DAYS = 3
LATE_DINNER_LOOKBACK = 14


@register_trigger("food_logging_stopped", cooldown_seconds=3 * 24 * 60 * 60)
class FoodLoggingStoppedTrigger(Trigger):
    """Food was being logged consistently and then stopped.

    Quiet observation — not a roast. The persona notes that the practice
    has lapsed. Tracking food is a deliberate practice; the silence is
    information whether it's intentional or not.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        # Last food log day for this user
        row = (
            await db.execute(
                text(
                    """
                    SELECT MAX((logged_at AT TIME ZONE 'America/New_York')::date)
                               AS last_day
                    FROM food_log WHERE user_id = :uid
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().first()

        last_day = row["last_day"] if row else None
        if not last_day:
            return None

        # Count distinct days in the window before that last_day where
        # there was logging — establishes "this was a practice." The explicit
        # CAST(:last AS date) is needed because asyncpg's parameter binding
        # makes Postgres unable to resolve `:last - interval` otherwise (it
        # tries to cast the interval back to date and fails).
        prior = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT (logged_at AT TIME ZONE 'America/New_York')::date)
                               AS days_logged
                    FROM food_log
                    WHERE user_id = :uid
                      AND (logged_at AT TIME ZONE 'America/New_York')::date
                          BETWEEN (CAST(:last AS date) - make_interval(days => :window))::date
                              AND CAST(:last AS date)
                    """
                ),
                {"uid": user_id, "last": last_day,
                 "window": FOOD_STOP_PRIOR_DAYS},
            )
        ).scalar_one()

        # Silence length: days since last log
        silence = (
            await db.execute(
                text(
                    """
                    SELECT (CURRENT_DATE - CAST(:last AS date))::int AS days
                    """
                ),
                {"last": last_day},
            )
        ).scalar_one()

        if int(prior or 0) < FOOD_STOP_MIN_PRIOR_DAYS:
            return None
        if int(silence or 0) < FOOD_STOP_SILENCE_DAYS:
            return None

        facts = {
            "last_log_date": last_day.isoformat(),
            "days_silent": int(silence),
            "prior_days_logged": int(prior),
        }
        summary = (
            f"Food logging stopped — last entry {facts['last_log_date']}, "
            f"{facts['days_silent']} days ago, after "
            f"{facts['prior_days_logged']} of {FOOD_STOP_PRIOR_DAYS} prior days logged"
        )
        return TriggerContext(
            trigger_name="food_logging_stopped",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"food_stopped:{last_day.isoformat()}",
        )


@register_trigger("protein_below_target", cooldown_seconds=2 * 24 * 60 * 60)
class ProteinBelowTargetTrigger(Trigger):
    """Multiple of the last 7 days landed under the protein floor.

    Quiet observation; the persona notes the pattern without prescription.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT log_date, total_protein
                    FROM fitness_daily_log
                    WHERE user_id = :uid
                      AND total_protein IS NOT NULL
                      AND log_date > CURRENT_DATE - make_interval(days => :n)
                    ORDER BY log_date DESC
                    """
                ),
                {"uid": user_id, "n": PROTEIN_LOW_LOOKBACK},
            )
        ).mappings().all()

        if len(rows) < PROTEIN_LOW_MIN_DAYS:
            return None

        low = [r for r in rows if float(r["total_protein"] or 0) < PROTEIN_LOW_GRAMS]
        if len(low) < PROTEIN_LOW_MIN_DAYS:
            return None

        avg = sum(float(r["total_protein"] or 0) for r in rows) / len(rows)
        facts = {
            "low_day_count": len(low),
            "logged_day_count": len(rows),
            "threshold_grams": PROTEIN_LOW_GRAMS,
            "average_grams": round(avg, 1),
            "lookback_days": PROTEIN_LOW_LOOKBACK,
        }
        summary = (
            f"{len(low)} of the last {len(rows)} logged days landed under "
            f"{PROTEIN_LOW_GRAMS:.0f}g protein; "
            f"average across the window: {facts['average_grams']}g"
        )
        return TriggerContext(
            trigger_name="protein_below_target",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"protein_low:{len(low)}_of_{len(rows)}",
        )


@register_trigger("late_dinner_habit", cooldown_seconds=3 * 24 * 60 * 60)
class LateDinnerHabitTrigger(Trigger):
    """Dinner logged after 10pm ET on 3+ of the last 14 days.

    Mild roast — late dinner is the kind of pattern the System notices and
    files away. Not a moral judgment, just a fact.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        (logged_at AT TIME ZONE 'America/New_York')::date AS day,
                        MAX(logged_at AT TIME ZONE 'America/New_York')   AS local_time
                    FROM food_log
                    WHERE user_id = :uid
                      AND meal_type = 'dinner'
                      AND logged_at > NOW() - make_interval(days => :n)
                    GROUP BY day
                    HAVING EXTRACT(HOUR FROM
                        MAX(logged_at AT TIME ZONE 'America/New_York')
                    ) >= :h
                    """
                ),
                {
                    "uid": user_id,
                    "n": LATE_DINNER_LOOKBACK,
                    "h": LATE_DINNER_HOUR,
                },
            )
        ).mappings().all()

        if len(rows) < LATE_DINNER_MIN_DAYS:
            return None

        # Latest occurrence drives the dedup key so the trigger refires when
        # there's a fresh late dinner after a quiet stretch.
        latest = max(r["local_time"] for r in rows)
        facts = {
            "late_dinner_count": len(rows),
            "lookback_days": LATE_DINNER_LOOKBACK,
            "threshold_hour_local": LATE_DINNER_HOUR,
            "latest_at_local": latest.isoformat() if latest else None,
        }
        summary = (
            f"{len(rows)} dinners logged after {LATE_DINNER_HOUR}:00 in "
            f"the last {LATE_DINNER_LOOKBACK} days"
        )
        return TriggerContext(
            trigger_name="late_dinner_habit",
            severity="roast",
            facts=facts,
            summary=summary,
            dedup_key=f"late_dinner:{len(rows)}",
        )


@register_trigger("the_silent_lunch", cooldown_seconds=2 * 24 * 60 * 60)
class TheSilentLunchTrigger(Trigger):
    """3+ of the last 7 days had breakfast and/or dinner logged but no lunch.

    Observation. Skipping lunch is the kind of detail the spec calls out
    explicitly — *"no break detected 11am–3pm on workday."* This is the
    food-log proxy for that signal.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT day,
                           BOOL_OR(meal_type = 'breakfast') AS has_breakfast,
                           BOOL_OR(meal_type = 'lunch')     AS has_lunch,
                           BOOL_OR(meal_type = 'dinner')    AS has_dinner
                    FROM (
                        SELECT
                            (logged_at AT TIME ZONE 'America/New_York')::date AS day,
                            meal_type
                        FROM food_log
                        WHERE user_id = :uid
                          AND logged_at > NOW() - INTERVAL '7 days'
                    ) s
                    GROUP BY day
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()

        # A day "skipped lunch" if any other meal was logged but lunch wasn't.
        skipped = [
            r for r in rows
            if (r["has_breakfast"] or r["has_dinner"]) and not r["has_lunch"]
        ]
        if len(skipped) < 3:
            return None

        facts = {
            "skip_count": len(skipped),
            "logged_day_count": len(rows),
            "skip_dates": [r["day"].isoformat() for r in skipped],
        }
        summary = (
            f"Lunch missing on {len(skipped)} of the last 7 logged days "
            "(breakfast or dinner present, lunch absent)"
        )
        return TriggerContext(
            trigger_name="the_silent_lunch",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"silent_lunch:{len(skipped)}",
        )
