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
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

_DAVID = get_owner_id()
# Recovery signals sync daily-ish and can lag a day; 40h keeps yesterday's
# morning HRV/RHR in play instead of throwing away the only reading we have.
_FRESH_HOURS = 40
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
    # Prefer the maintained baseline...
    r = (await db.execute(text("""
        SELECT average_value, std_deviation FROM health_baseline
        WHERE metric_type = :m AND average_value IS NOT NULL
        ORDER BY calculated_at DESC LIMIT 1
    """), {"m": metric_type})).first()
    if r and r[0] and r[1]:
        return (float(r[0]), float(r[1]))
    # ...but the baseline pipeline doesn't maintain the recovery signals (HRV/RHR/
    # respiratory), so fall back to a rolling baseline computed straight from the
    # raw metrics. This makes readiness self-sufficient instead of flat.
    roll = (await db.execute(text("""
        SELECT AVG(value)::float, STDDEV_SAMP(value)::float, COUNT(*)
        FROM health_metric
        WHERE metric_type = :m
          AND recorded_at >= NOW() - INTERVAL '60 days'
    """), {"m": metric_type})).first()
    if roll and roll[0] is not None and roll[1] and roll[2] and roll[2] >= 5:
        return (float(roll[0]), float(roll[1]))
    return None


def _z(value: float, base: Tuple[float, float]) -> Optional[float]:
    avg, std = base
    if not std:
        return None
    return (value - avg) / std


async def compute_readiness(db, user_id: str = _DAVID) -> dict:
    """Compute and persist today's readiness. Returns the result dict."""
    contributions: List[Tuple[str, float, str]] = []  # (label, delta, driver_text)
    score = 70.0  # neutral baseline

    # Use the metric-type names that actually exist in health_metric:
    # hrv_morning is the fresh daily reading (raw `hrv` is stale); RHR is
    # `resting_hr` (NOT resting_heart_rate — the name mismatch meant RHR never
    # contributed).
    sleep = await _latest_metric(db, "sleep_hours")
    hrv = await _latest_metric(db, "hrv_morning") or await _latest_metric(db, "hrv")
    rhr = await _latest_metric(db, "resting_hr") or await _latest_metric(db, "resting_heart_rate")
    resp = await _latest_metric(db, "respiratory_rate")

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
        b = await _baseline(db, "resting_hr") or await _baseline(db, "resting_heart_rate")
        if b:
            z = _z(rhr_val, b)
            if z is not None:
                delta = max(-15, min(10, -z * 8))
                score += delta
                if z >= 0.7:
                    contributions.append(("rhr", delta, f"elevated resting HR ({rhr_val:.0f})"))

    # Respiratory rate: elevated overnight breathing = poorer recovery / oncoming
    # illness. Only contributes when there's a personal baseline to compare to.
    resp_val = None
    if resp:
        resp_val = resp[0]
        b = await _baseline(db, "respiratory_rate")
        if b:
            z = _z(resp_val, b)
            if z is not None and z >= 0.8:
                delta = max(-10, -z * 5)
                score += delta
                contributions.append(("resp", delta, "elevated respiratory rate"))

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
