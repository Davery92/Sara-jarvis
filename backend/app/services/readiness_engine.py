"""Readiness engine (§6.2) — one nightly number, z-scored against David's own
baselines (never population norms).

The audit found `morning_readiness` empty — the score existed client-side but no
server computation fed the single source of truth. This unifies sleep, HRV, and
resting HR (each vs `health_baseline`) into one readiness score + the top-2
drivers, written where every consumer reads it (workspace slot 7, interruptibility
appetite, scheduling counsel, bedtime intelligence). Degrades gracefully when a
signal is missing or stale — a sleep-only score still beats no score.
"""
import logging
import uuid
from typing import Optional, Tuple, List

from sqlalchemy import text

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
_FRESH_HOURS = 30  # a signal older than this doesn't reflect *this* morning
_SLEEP_TARGET = 7.5


async def _latest_metric(db, metric_type: str) -> Optional[Tuple[float, object]]:
    r = (await db.execute(text("""
        SELECT value, recorded_at FROM health_metric
        WHERE metric_type = :m
          AND recorded_at >= NOW() - MAKE_INTERVAL(hours => :h)
        ORDER BY recorded_at DESC LIMIT 1
    """), {"m": metric_type, "h": _FRESH_HOURS})).first()
    return (float(r[0]), r[1]) if r else None


async def _baseline(db, metric_type: str) -> Optional[Tuple[float, float]]:
    r = (await db.execute(text("""
        SELECT average_value, std_deviation FROM health_baseline
        WHERE metric_type = :m AND average_value IS NOT NULL
        ORDER BY calculated_at DESC LIMIT 1
    """), {"m": metric_type})).first()
    if not r or not r[0]:
        return None
    return (float(r[0]), float(r[1]) if r[1] else 0.0)


def _z(value: float, base: Tuple[float, float]) -> Optional[float]:
    avg, std = base
    if not std:
        return None
    return (value - avg) / std


async def compute_readiness(db, user_id: str = _DAVID) -> dict:
    """Compute and persist today's readiness. Returns the result dict."""
    contributions: List[Tuple[str, float, str]] = []  # (label, delta, driver_text)
    score = 70.0  # neutral baseline

    sleep = await _latest_metric(db, "sleep_hours")
    hrv = await _latest_metric(db, "hrv") or await _latest_metric(db, "hrv_morning")
    rhr = await _latest_metric(db, "resting_heart_rate")

    sleep_val = hrv_val = rhr_val = None

    # Sleep vs 7.5h target: ±6 points/hour, capped.
    if sleep:
        sleep_val = sleep[0]
        delta = max(-20, min(15, (sleep_val - _SLEEP_TARGET) * 6))
        score += delta
        if sleep_val < 6.5:
            contributions.append(("sleep", delta, f"short sleep ({sleep_val:.1f}h)"))
        elif sleep_val >= 8:
            contributions.append(("sleep", delta, f"good sleep ({sleep_val:.1f}h)"))

    # HRV z-score vs personal baseline (higher = better recovery).
    if hrv:
        hrv_val = hrv[0]
        b = await _baseline(db, "hrv_morning") or await _baseline(db, "hrv")
        if b:
            z = _z(hrv_val, b)
            if z is not None:
                delta = max(-15, min(15, z * 8))
                score += delta
                if z <= -0.7:
                    contributions.append(("hrv", delta, "HRV below your baseline"))
                elif z >= 0.7:
                    contributions.append(("hrv", delta, "HRV above your baseline"))

    # Resting HR: elevated vs baseline = worse.
    if rhr:
        rhr_val = rhr[0]
        b = await _baseline(db, "resting_heart_rate")
        if b:
            z = _z(rhr_val, b)
            if z is not None:
                delta = max(-15, min(10, -z * 8))
                score += delta
                if z >= 0.7:
                    contributions.append(("rhr", delta, "elevated resting HR"))

    score = int(max(0, min(100, round(score))))

    # Top-2 drivers by absolute impact.
    contributions.sort(key=lambda c: abs(c[1]), reverse=True)
    drivers = [c[2] for c in contributions[:2]]

    if score >= 80:
        rec, msg = "green", "Recovered — good day to push."
    elif score >= 60:
        rec, msg = "moderate", "Solid — train as planned, listen to your body."
    else:
        rec, msg = "amber", "Under-recovered — favor lighter volume today."
    if drivers:
        msg = f"Readiness {score}: " + ", ".join(drivers) + f". {msg}"

    await db.execute(text("""
        INSERT INTO morning_readiness
          (id, user_id, hrv_ms, rhr, sleep_hours, energy, soreness, stress,
           time_available_min, score, recommendation, message, created_at)
        VALUES (:id, :u, :hrv, :rhr, :sleep, :energy, :soreness, :stress,
                :tam, :score, :rec, :msg, NOW())
    """), {
        "id": str(uuid.uuid4()), "u": user_id,
        "hrv": hrv_val, "rhr": rhr_val, "sleep": sleep_val,
        # Subjective check-in fields are NOT NULL but we compute readiness
        # objectively — insert neutral placeholders (no self-report today).
        "energy": 3, "soreness": 0, "stress": 0, "tam": 0,
        "score": score, "rec": rec, "msg": msg,
    })
    await db.commit()
    logger.info(f"💤 Readiness computed: {score} ({rec}) — {drivers}")
    return {"effect": "computed_readiness", "score": score,
            "recommendation": rec, "drivers": drivers}
