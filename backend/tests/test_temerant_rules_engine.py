from datetime import date, datetime, timezone

from app.services.temerant.rules_engine import TemerantRulesEngine


def test_map_manual_action_known_rule():
    mapped = TemerantRulesEngine.map_manual_action("workout")
    assert mapped.attribute == "body"
    assert mapped.xp_delta == 2
    assert mapped.subdomain == "training"


def test_map_manual_action_unknown_falls_back_to_general():
    mapped = TemerantRulesEngine.map_manual_action("unknown_action_type")
    assert mapped.attribute == "mind"
    assert mapped.xp_delta == 1
    assert mapped.subdomain == "general"


def test_map_manual_action_scales_with_quantity_and_clamps():
    mapped = TemerantRulesEngine.map_manual_action("coding", quantity=20)
    # Base 3 + max clamp of +3.
    assert mapped.xp_delta == 6


def test_apply_daily_cap_when_under_cap():
    applied = TemerantRulesEngine.apply_daily_cap("mind", current_xp_today=4, xp_delta=5)
    assert applied == 5


def test_apply_daily_cap_when_partially_capped():
    applied = TemerantRulesEngine.apply_daily_cap("mind", current_xp_today=13, xp_delta=5)
    assert applied == 2


def test_apply_daily_cap_when_fully_capped():
    applied = TemerantRulesEngine.apply_daily_cap("mind", current_xp_today=15, xp_delta=5)
    assert applied == 0


def test_admissions_thresholds():
    assert TemerantRulesEngine.admissions_from_completion(80.0) == ("excellent", 5, 1.5)
    assert TemerantRulesEngine.admissions_from_completion(60.0) == ("good", 10, 1.0)
    assert TemerantRulesEngine.admissions_from_completion(30.0) == ("poor", 15, 1.0)
    assert TemerantRulesEngine.admissions_from_completion(29.9) == ("terrible", 20, 0.9)


def test_term_month_for_first_day():
    assert TemerantRulesEngine.term_month_for(date(2026, 2, 20)) == date(2026, 2, 1)


def test_idempotency_key_stable_and_sensitive_to_input():
    occurred_at = datetime(2026, 2, 20, 12, 0, tzinfo=timezone.utc)

    key_a = TemerantRulesEngine.build_idempotency_key(
        user_id="u1",
        source_type="manual",
        source_ref_id="s1",
        occurred_at=occurred_at,
        action_type="workout",
        quantity=1,
    )
    key_b = TemerantRulesEngine.build_idempotency_key(
        user_id="u1",
        source_type="manual",
        source_ref_id="s1",
        occurred_at=occurred_at,
        action_type="workout",
        quantity=1,
    )
    key_c = TemerantRulesEngine.build_idempotency_key(
        user_id="u1",
        source_type="manual",
        source_ref_id="s1",
        occurred_at=occurred_at,
        action_type="workout",
        quantity=2,
    )

    assert key_a == key_b
    assert key_a != key_c
    assert key_a.startswith("temerant:")


def test_infer_action_type_from_keywords():
    assert TemerantRulesEngine.infer_action_type("Upper body workout") == "workout"
    assert TemerantRulesEngine.infer_action_type("Neural network study block") == "study"
    assert TemerantRulesEngine.infer_action_type("Guitar practice") == "guitar"


def test_infer_action_type_fallback():
    assert TemerantRulesEngine.infer_action_type("random unrelated title", fallback="coding") == "coding"
