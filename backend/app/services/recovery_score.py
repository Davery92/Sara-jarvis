"""Single source of truth for the recovery / readiness score (0-100).

This used to be implemented twice — here-ish (inline in morning_brief_service)
and again in TypeScript (ios-app/src/utils/recovery.ts) — kept in sync only by
a comment. Now the weights live here; the morning brief calls this, the recovery
API returns the result, and the iOS app just displays it.

A `baseline` is the average of a recent window (HRV / resting-HR are scored
relative to it). Pass {} when no baseline is available — those factors are then
skipped, exactly as before.
"""

from typing import Dict, List, Optional


def compute_readiness(recovery: Dict, baseline: Optional[Dict] = None) -> Dict:
    """Score one day's recovery against a baseline.

    `recovery` keys: sleep_hours, hrv, heart_rate, soreness_level (any may be None).
    `baseline` keys: avg_hrv, avg_hr (optional).
    Returns {score, label, status, color, factors}.
    """
    baseline = baseline or {}
    score = 100
    factors: List[str] = []

    # Sleep (target 7-8 hrs)
    sleep = recovery.get("sleep_hours")
    if sleep:
        if sleep < 6:
            score -= 30
            factors.append(f"only {sleep:.1f}h sleep")
        elif sleep < 7:
            score -= 15
            factors.append(f"{sleep:.1f}h sleep")
        elif sleep > 9:
            score -= 5

    # HRV vs baseline
    hrv = recovery.get("hrv")
    avg_hrv = baseline.get("avg_hrv")
    if hrv and avg_hrv:
        diff = hrv - avg_hrv
        if diff < -15:
            score -= 25
            factors.append(f"HRV {abs(diff):.0f}ms below baseline")
        elif diff < -8:
            score -= 12
            factors.append("HRV slightly below baseline")

    # Resting HR vs baseline (elevated = poorer recovery)
    hr = recovery.get("heart_rate")
    avg_hr = baseline.get("avg_hr")
    if hr and avg_hr:
        diff = hr - avg_hr
        if diff > 10:
            score -= 20
            factors.append(f"elevated resting HR ({hr} bpm)")
        elif diff > 5:
            score -= 10

    # Soreness
    soreness = recovery.get("soreness_level")
    if soreness:
        if soreness >= 8:
            score -= 15
            factors.append(f"high soreness ({soreness}/10)")
        elif soreness >= 6:
            score -= 10
            factors.append(f"moderate soreness ({soreness}/10)")
        elif soreness >= 4:
            score -= 5

    score = max(0, min(100, round(score)))

    if score >= 85:
        label, status, color = "Excellent", "Well recovered — good to push it today", "success"
    elif score >= 70:
        label, status, color = "Good", "Moderate recovery — train but listen to your body", "primary"
    elif score >= 50:
        label, status, color = "Low", "Low recovery — consider lighter weights", "warning"
    else:
        label, status, color = "Poor", "Poor recovery — rest day recommended", "error"

    return {"score": score, "label": label, "status": status, "color": color, "factors": factors}
