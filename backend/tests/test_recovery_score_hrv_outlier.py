"""
gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 5 §2: Sunday's HRV 153
(2-sample reading vs a 48-75 baseline) scored as "recovery looks solid".
"""
from app.services.recovery_score import compute_readiness


def test_hrv_outlier_is_not_scored_against_baseline():
    result = compute_readiness({"hrv": 153, "sleep_hours": 7.5}, baseline={"avg_hrv": 60})
    assert not any("below baseline" in f for f in result["factors"])
    assert any("unverified" in f for f in result["factors"])


def test_normal_hrv_still_scores_against_baseline():
    result = compute_readiness({"hrv": 40, "sleep_hours": 7.5}, baseline={"avg_hrv": 60})
    assert any("below baseline" in f for f in result["factors"])
