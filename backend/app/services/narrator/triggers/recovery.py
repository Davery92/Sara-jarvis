"""Recovery metric triggers — HRV, resting HR, weight, sleep architecture.

All baselines are computed in-query against `health_metric`. Most signals
use a "recent N days vs prior M-day baseline" structure so they fire on
*shifts*, not absolute thresholds — David's normal is not the population's
normal.
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


# Resting HR
RHR_BASELINE_DAYS = 30
RHR_RECENT_DAYS = 5
RHR_DELTA_BPM = 5         # bpm above baseline counts as "elevated"
RHR_MIN_HIGH_DAYS = 3     # of the last 5 days

# Morning HRV
HRV_BASELINE_DAYS = 30
HRV_RECENT_DAYS = 5
HRV_DROP_RATIO = 0.85     # recent < 85% of baseline
HRV_MIN_LOW_DAYS = 3

# Body weight swing
WEIGHT_SWING_HOURS = 48
WEIGHT_SWING_PCT = 0.02   # 2% body weight in 48h

# Deep sleep drought
DEEP_SLEEP_MIN_MINUTES = 60
DEEP_SLEEP_LOW_NIGHTS = 3
DEEP_SLEEP_LOOKBACK = 5


@register_trigger("resting_hr_elevated", cooldown_seconds=2 * 24 * 60 * 60)
class RestingHRElevatedTrigger(Trigger):
    """Resting heart rate consistently above its 30-day baseline.

    Observation — elevated RHR can mean illness, stress, or just heat.
    The persona reports the signal, not the diagnosis.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        # Pre-compute the window total so we pass a single int param. Adding
        # two bound int params inline (`$1 + $2`) makes asyncpg surface them
        # as `unknown + unknown` and Postgres can't pick an operator.
        total_window = RHR_BASELINE_DAYS + RHR_RECENT_DAYS
        row = (
            await db.execute(
                text(
                    """
                    WITH daily AS (
                        SELECT
                            (recorded_at AT TIME ZONE 'America/New_York')::date AS day,
                            AVG(value) AS bpm
                        FROM health_metric
                        WHERE user_id = :uid
                          AND metric_type = 'resting_hr'
                          AND recorded_at > NOW() - make_interval(days => :total)
                        GROUP BY day
                    )
                    SELECT
                        AVG(bpm) FILTER (
                            WHERE day <= CURRENT_DATE - make_interval(days => :recent)
                        ) AS baseline,
                        COUNT(*) FILTER (
                            WHERE day > CURRENT_DATE - make_interval(days => :recent)
                        ) AS recent_n,
                        AVG(bpm) FILTER (
                            WHERE day > CURRENT_DATE - make_interval(days => :recent)
                        ) AS recent_avg,
                        ARRAY_AGG(bpm ORDER BY day DESC) FILTER (
                            WHERE day > CURRENT_DATE - make_interval(days => :recent)
                        ) AS recent_values
                    FROM daily
                    """
                ),
                {
                    "uid": user_id,
                    "total": total_window,
                    "recent": RHR_RECENT_DAYS,
                },
            )
        ).mappings().first()

        if (not row or not row["baseline"] or not row["recent_avg"]
                or int(row["recent_n"] or 0) < 3):
            return None

        baseline = float(row["baseline"])
        recent_values = [float(v) for v in (row["recent_values"] or [])]
        threshold = baseline + RHR_DELTA_BPM
        high = [v for v in recent_values if v > threshold]
        if len(high) < RHR_MIN_HIGH_DAYS:
            return None

        facts = {
            "baseline_bpm": round(baseline, 1),
            "recent_avg_bpm": round(float(row["recent_avg"]), 1),
            "high_day_count": len(high),
            "recent_day_count": int(row["recent_n"]),
            "delta_threshold_bpm": RHR_DELTA_BPM,
        }
        summary = (
            f"Resting HR averaging {facts['recent_avg_bpm']} bpm over the "
            f"last {facts['recent_day_count']} days vs "
            f"{facts['baseline_bpm']} bpm baseline; "
            f"{len(high)} days above +{RHR_DELTA_BPM} bpm"
        )
        return TriggerContext(
            trigger_name="resting_hr_elevated",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"rhr_elevated:{int(facts['recent_avg_bpm'])}",
        )


@register_trigger("hrv_depression", cooldown_seconds=2 * 24 * 60 * 60)
class HRVDepressionTrigger(Trigger):
    """Morning HRV running below ~85% of the 30-day baseline.

    Observation — low HRV is a recovery signal worth flagging. The persona
    notes the drop without prescribing rest.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        total_window = HRV_BASELINE_DAYS + HRV_RECENT_DAYS
        row = (
            await db.execute(
                text(
                    """
                    WITH daily AS (
                        SELECT
                            (recorded_at AT TIME ZONE 'America/New_York')::date AS day,
                            AVG(value) AS hrv
                        FROM health_metric
                        WHERE user_id = :uid
                          AND metric_type IN ('hrv_morning', 'hrv')
                          AND recorded_at > NOW() - make_interval(days => :total)
                        GROUP BY day
                    )
                    SELECT
                        AVG(hrv) FILTER (
                            WHERE day <= CURRENT_DATE - make_interval(days => :recent)
                        ) AS baseline,
                        COUNT(*) FILTER (
                            WHERE day > CURRENT_DATE - make_interval(days => :recent)
                        ) AS recent_n,
                        AVG(hrv) FILTER (
                            WHERE day > CURRENT_DATE - make_interval(days => :recent)
                        ) AS recent_avg,
                        ARRAY_AGG(hrv ORDER BY day DESC) FILTER (
                            WHERE day > CURRENT_DATE - make_interval(days => :recent)
                        ) AS recent_values
                    FROM daily
                    """
                ),
                {
                    "uid": user_id,
                    "total": total_window,
                    "recent": HRV_RECENT_DAYS,
                },
            )
        ).mappings().first()

        if (not row or not row["baseline"] or not row["recent_avg"]
                or int(row["recent_n"] or 0) < 3):
            return None

        baseline = float(row["baseline"])
        recent_avg = float(row["recent_avg"])
        recent_values = [float(v) for v in (row["recent_values"] or [])]
        floor = baseline * HRV_DROP_RATIO
        low = [v for v in recent_values if v < floor]
        if len(low) < HRV_MIN_LOW_DAYS:
            return None

        facts = {
            "baseline_hrv": round(baseline, 1),
            "recent_avg_hrv": round(recent_avg, 1),
            "low_day_count": len(low),
            "recent_day_count": int(row["recent_n"]),
            "drop_ratio_threshold": HRV_DROP_RATIO,
            "drop_pct": round((1 - recent_avg / baseline) * 100, 1),
        }
        summary = (
            f"Morning HRV averaging {facts['recent_avg_hrv']} vs "
            f"{facts['baseline_hrv']} baseline "
            f"(-{facts['drop_pct']}%); "
            f"{len(low)} of {facts['recent_day_count']} days below the floor"
        )
        return TriggerContext(
            trigger_name="hrv_depression",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"hrv_depression:{int(facts['drop_pct']/5)*5}",
        )


@register_trigger("body_weight_swing", cooldown_seconds=24 * 60 * 60)
class BodyWeightSwingTrigger(Trigger):
    """Body weight moved ≥2% in the last 48 hours.

    Observation — a quick swing is usually water or food load, not body
    composition. The persona reports the magnitude, not the cause.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        # Latest weight + the weight from ~48h ago for the same user.
        # Pre-compute hours window to dodge the `unknown + unknown` issue.
        hours_window = WEIGHT_SWING_HOURS + 12
        rows = (
            await db.execute(
                text(
                    """
                    SELECT recorded_at, value::float AS weight
                    FROM health_metric
                    WHERE user_id = :uid
                      AND metric_type = 'weight'
                      AND recorded_at > NOW() - make_interval(hours => :hours)
                    ORDER BY recorded_at DESC
                    """
                ),
                {"uid": user_id, "hours": hours_window},
            )
        ).mappings().all()

        if len(rows) < 2:
            return None

        latest = rows[0]
        # Find the oldest row within the swing window. We want comparison
        # against the earliest reading in the window, not the second-latest,
        # so a 48h swing is captured even with multiple intermediate readings.
        earliest_in_window = rows[-1]
        from datetime import timedelta
        for r in reversed(rows):
            if (latest["recorded_at"] - r["recorded_at"]) <= timedelta(hours=WEIGHT_SWING_HOURS):
                earliest_in_window = r
                break

        latest_w = float(latest["weight"])
        prior_w = float(earliest_in_window["weight"])
        if prior_w <= 0:
            return None

        delta = latest_w - prior_w
        pct = abs(delta) / prior_w
        if pct < WEIGHT_SWING_PCT:
            return None

        facts = {
            "latest_weight": round(latest_w, 1),
            "prior_weight": round(prior_w, 1),
            "delta": round(delta, 2),
            "delta_pct": round(pct * 100, 2),
            "hours_between": round(
                (latest["recorded_at"] - earliest_in_window["recorded_at"]).total_seconds() / 3600, 1
            ),
        }
        direction = "up" if delta > 0 else "down"
        summary = (
            f"Body weight {direction} {abs(facts['delta'])} lb "
            f"({facts['delta_pct']}%) over {facts['hours_between']}h "
            f"({prior_w:.1f} → {latest_w:.1f})"
        )
        return TriggerContext(
            trigger_name="body_weight_swing",
            severity="observation",
            facts=facts,
            summary=summary,
            # Bucket by direction + integer percent so small wiggles don't refire.
            dedup_key=f"weight_swing:{direction}:{int(pct*100)}",
        )


@register_trigger("deep_sleep_drought", cooldown_seconds=2 * 24 * 60 * 60)
class DeepSleepDroughtTrigger(Trigger):
    """Deep sleep under 60 minutes on 3+ of the last 5 nights.

    Observation. Sleep gets tact, not contempt.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        (recorded_at AT TIME ZONE 'America/New_York')::date AS day,
                        AVG(value) AS deep_min
                    FROM health_metric
                    WHERE user_id = :uid
                      AND metric_type = 'sleep_deep_min'
                      AND recorded_at > NOW() - make_interval(days => :n)
                    GROUP BY day
                    ORDER BY day DESC
                    LIMIT :n
                    """
                ),
                {"uid": user_id, "n": DEEP_SLEEP_LOOKBACK},
            )
        ).mappings().all()

        if len(rows) < DEEP_SLEEP_LOW_NIGHTS:
            return None

        low = [r for r in rows if float(r["deep_min"] or 0) < DEEP_SLEEP_MIN_MINUTES]
        if len(low) < DEEP_SLEEP_LOW_NIGHTS:
            return None

        avg = sum(float(r["deep_min"] or 0) for r in rows) / len(rows)
        facts = {
            "low_night_count": len(low),
            "lookback_nights": len(rows),
            "threshold_minutes": DEEP_SLEEP_MIN_MINUTES,
            "average_minutes": round(avg, 1),
            "values": [round(float(r["deep_min"] or 0), 1) for r in rows],
        }
        summary = (
            f"Deep sleep under {DEEP_SLEEP_MIN_MINUTES}min on {len(low)} of "
            f"the last {len(rows)} nights; average {facts['average_minutes']}min"
        )
        return TriggerContext(
            trigger_name="deep_sleep_drought",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"deep_sleep:{len(low)}_of_{len(rows)}",
        )
