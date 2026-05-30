"""Activity triggers from health_metric (steps, flights, exercise minutes)."""
from __future__ import annotations

import logging
from datetime import timedelta
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


SEDENTARY_STEP_THRESHOLD = 3000     # daily step floor for "sedentary"
SEDENTARY_MIN_STREAK = 3            # consecutive days below floor

STEP_COLLAPSE_RECENT_DAYS = 7       # window for recent average
STEP_COLLAPSE_BASELINE_DAYS = 28    # window for prior baseline
STEP_COLLAPSE_RATIO = 0.5           # recent < 50% of baseline = collapse

# Flights-climbed milestones — bucketed to "interesting numbers."
FLIGHTS_DAY_MILESTONES = (25, 50, 100)


@register_trigger("sedentary_streak", cooldown_seconds=24 * 60 * 60)
class SedentaryStreakTrigger(Trigger):
    """3+ consecutive days under 3000 steps.

    Observation, not roast — rest days happen, and the persona doesn't
    moralize about movement. But a multi-day streak crosses from "rest"
    into "pattern" and that's worth noting.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        # Daily step totals for the last 10 *completed* days. Apple Health
        # samples are CUMULATIVE daily snapshots (metadata.cumulative=true), so
        # the day's total is MAX(value), not SUM. Today is excluded because its
        # cumulative count is still climbing and would read as falsely low.
        rows = (
            await db.execute(
                text(
                    """
                    SELECT day, MAX(value)::int AS steps
                    FROM (
                        SELECT
                            (recorded_at AT TIME ZONE 'America/New_York')::date AS day,
                            value
                        FROM health_metric
                        WHERE user_id = :uid
                          AND metric_type = 'steps'
                          AND recorded_at > NOW() - INTERVAL '10 days'
                    ) s
                    WHERE day < :today
                    GROUP BY day
                    ORDER BY day DESC
                    LIMIT 7
                    """
                ),
                {"uid": user_id, "today": et_today()},
            )
        ).mappings().all()

        if not rows:
            return None

        # Walk newest-to-oldest counting the consecutive low days.
        streak = 0
        low_days = []
        for r in rows:
            if int(r["steps"]) < SEDENTARY_STEP_THRESHOLD:
                streak += 1
                low_days.append(
                    {"date": r["day"].isoformat(), "steps": int(r["steps"])}
                )
            else:
                break

        if streak < SEDENTARY_MIN_STREAK:
            return None

        facts = {
            "streak_days": streak,
            "step_threshold": SEDENTARY_STEP_THRESHOLD,
            "low_days": low_days,
        }
        summary = (
            f"{streak} consecutive days under {SEDENTARY_STEP_THRESHOLD} steps"
        )
        return TriggerContext(
            trigger_name="sedentary_streak",
            severity="observation",
            facts=facts,
            summary=summary,
            # Key on the most-recent low day so the streak is noted at most
            # once per new low day, not re-fired every 30-minute sweep.
            dedup_key=f"sedentary_streak:{low_days[0]['date']}",
        )


@register_trigger("step_count_collapse", cooldown_seconds=3 * 24 * 60 * 60)
class StepCountCollapseTrigger(Trigger):
    """Recent 7-day average is <50% of the prior 28-day average.

    Quiet observation — a sharp drop is information, not a verdict. The
    persona doesn't speculate about the cause.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        total_window = STEP_COLLAPSE_RECENT_DAYS + STEP_COLLAPSE_BASELINE_DAYS
        today = et_today()
        row = (
            await db.execute(
                text(
                    """
                    WITH daily AS (
                        SELECT (recorded_at AT TIME ZONE 'America/New_York')::date AS day,
                               MAX(value)::int AS steps
                        FROM health_metric
                        WHERE user_id = :uid
                          AND metric_type = 'steps'
                          AND recorded_at > NOW() - make_interval(days => :total)
                        GROUP BY day
                    )
                    SELECT
                        AVG(steps) FILTER (
                            WHERE day >= :recent_cutoff AND day < :today
                        ) AS recent_avg,
                        AVG(steps) FILTER (
                            WHERE day < :recent_cutoff
                        ) AS prior_avg,
                        COUNT(*) FILTER (
                            WHERE day >= :recent_cutoff AND day < :today
                        ) AS recent_n,
                        COUNT(*) FILTER (
                            WHERE day < :recent_cutoff
                        ) AS prior_n
                    FROM daily
                    """
                ),
                {
                    "uid": user_id,
                    "total": total_window,
                    "today": today,
                    "recent_cutoff": today - timedelta(days=STEP_COLLAPSE_RECENT_DAYS),
                },
            )
        ).mappings().first()

        # Require enough data on both sides to be meaningful.
        if not row or int(row["recent_n"] or 0) < 5 or int(row["prior_n"] or 0) < 14:
            return None
        if not row["recent_avg"] or not row["prior_avg"]:
            return None

        recent = float(row["recent_avg"])
        prior = float(row["prior_avg"])
        if recent >= prior * STEP_COLLAPSE_RATIO:
            return None

        facts = {
            "recent_avg_steps": int(recent),
            "baseline_avg_steps": int(prior),
            "recent_days": int(row["recent_n"]),
            "baseline_days": int(row["prior_n"]),
            "drop_ratio": round(recent / prior, 2),
        }
        summary = (
            f"Steps collapsed: 7-day avg {int(recent)} vs prior 4-week avg "
            f"{int(prior)} ({facts['drop_ratio']*100:.0f}% of baseline)"
        )
        return TriggerContext(
            trigger_name="step_count_collapse",
            severity="observation",
            facts=facts,
            summary=summary,
            # Bucket to the nearest 1000 so small day-to-day drift in the
            # rolling averages doesn't mint a new key and bypass the cooldown.
            dedup_key=f"step_collapse:{round(recent/1000)}_{round(prior/1000)}",
        )


@register_trigger("flights_climbed_milestone", cooldown_seconds=20 * 60 * 60)
class FlightsClimbedMilestoneTrigger(Trigger):
    """Single-day flights-climbed crossed a milestone (25/50/100).

    Achievement — David did the climb. The persona's deflected-praise
    register: brief, undercut.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT day, MAX(value)::int AS flights
                    FROM (
                        SELECT
                            (recorded_at AT TIME ZONE 'America/New_York')::date AS day,
                            value
                        FROM health_metric
                        WHERE user_id = :uid
                          AND metric_type = 'flights_climbed'
                          AND recorded_at > NOW() - INTERVAL '2 days'
                    ) s
                    GROUP BY day
                    ORDER BY day DESC
                    LIMIT 1
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().first()

        if not row or int(row["flights"] or 0) < FLIGHTS_DAY_MILESTONES[0]:
            return None

        flights = int(row["flights"])
        crossed = max(m for m in FLIGHTS_DAY_MILESTONES if m <= flights)

        facts = {
            "day": row["day"].isoformat(),
            "flights": flights,
            "milestone_crossed": crossed,
        }
        summary = f"{flights} flights climbed on {row['day'].isoformat()}; crossed {crossed}"
        return TriggerContext(
            trigger_name="flights_climbed_milestone",
            severity="achievement",
            facts=facts,
            summary=summary,
            # One fire per (day, milestone) tier.
            dedup_key=f"flights:{row['day'].isoformat()}:{crossed}",
        )
