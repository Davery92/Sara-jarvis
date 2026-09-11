"""Regression for SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10 Phase 1
(Food actions): a planned/future meal ("dinner is going to be beef-heavy
taco pasta salad") must never become a consumed-food write, and a
model-constructed `user_input` that doesn't match what David actually said
must not be trusted as evidence of what he ate.

Both checks run before any DB/network access in `execute()`, so these tests
exercise the tool directly without stubbing FatSecret or the database.
"""

import uuid

import pytest

from app.tools.fitness.food_search_log import FoodSearchAndLogTool


@pytest.mark.asyncio
async def test_planned_meal_is_not_logged():
    tool = FoodSearchAndLogTool()
    result = await tool.execute(
        user_id="user-1",
        user_input="beef taco pasta salad",
        meal_type="dinner",
        _raw_user_turn="Dinner is going to be beef-heavy taco pasta salad",
    )
    assert result.success is False
    assert "plan" in result.message.lower()


@pytest.mark.asyncio
async def test_explicit_log_request_bypasses_plan_language():
    tool = FoodSearchAndLogTool()
    result = await tool.execute(
        user_id="user-1",
        user_input="3 eggs and bacon",
        meal_type="breakfast",
        _raw_user_turn="I'm planning on 3 eggs and bacon, log it",
    )
    # Should proceed past the plan/grounding gate (fails later on real
    # network access in this offline test, but not with a "plan" refusal).
    assert not (result.success is False and "plan" in result.message.lower())


@pytest.mark.asyncio
async def test_completed_tense_bypasses_plan_language():
    tool = FoodSearchAndLogTool()
    result = await tool.execute(
        user_id="user-1",
        user_input="3 eggs and bacon",
        meal_type="breakfast",
        _raw_user_turn="I just had 3 eggs and bacon",
    )
    assert not (result.success is False and "plan" in result.message.lower())


@pytest.mark.asyncio
async def test_ungrounded_user_input_is_rejected():
    tool = FoodSearchAndLogTool()
    result = await tool.execute(
        user_id="user-1",
        user_input="4oz grilled salmon and quinoa",
        meal_type="dinner",
        # David never mentioned salmon or quinoa.
        _raw_user_turn="Dinner is going to be beef-heavy taco pasta salad",
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_no_raw_turn_skips_grounding_checks():
    tool = FoodSearchAndLogTool()
    result = await tool.execute(
        user_id="user-1",
        user_input="3 eggs",
        meal_type="breakfast",
    )
    # No raw turn to check against (e.g. non-chat origin) — must not be
    # rejected for "plan" or "doesn't match" reasons.
    assert not (result.success is False and "plan" in result.message.lower())
    assert not (result.success is False and "doesn't match" in result.message.lower())


@pytest.mark.asyncio
async def test_retracted_entry_is_not_recreated():
    """Conversation competence plan Phase 3: David deleting a fabricated
    entry and saying 'don't do that' must actually stop it from coming
    back — not just be acknowledged in the reply."""
    from app.services.corrections import record_food_log_retraction
    from app.db.session import get_async_session_factory

    user_id = f"test-food-retraction-{uuid.uuid4().hex[:12]}"
    try:
        async with get_async_session_factory()() as db:
            await record_food_log_retraction(db, user_id, "log-1", "dinner: beef taco pasta salad")
            await db.commit()

        tool = FoodSearchAndLogTool()
        result = await tool.execute(
            user_id=user_id,
            user_input="beef taco pasta salad",
            meal_type="dinner",
        )
        assert result.success is False
        assert "removed" in result.message.lower()
    finally:
        from sqlalchemy import text
        async with get_async_session_factory()() as db:
            await db.execute(text("DELETE FROM correction WHERE user_id = :uid"), {"uid": user_id})
            await db.commit()


class TestGroundedInUserTurn:
    def test_matching_words_pass(self):
        assert FoodSearchAndLogTool._grounded_in_user_turn(
            "4oz chicken breast and rice", "I had 4oz of chicken breast with some rice"
        )

    def test_invented_food_fails(self):
        assert not FoodSearchAndLogTool._grounded_in_user_turn(
            "grilled salmon and quinoa", "dinner is going to be taco pasta salad"
        )

    def test_missing_raw_turn_passes(self):
        assert FoodSearchAndLogTool._grounded_in_user_turn("anything at all", None)
