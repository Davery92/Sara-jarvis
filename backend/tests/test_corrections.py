"""Tests for app/services/corrections.py — SARA_CONVERSATION_COMPETENCE_
PLAN_2026_09_10 Phase 3 ("give corrections durable effects").

Runs against the real dev database (migration 151_correction) rather than
mocking every query: the module's idempotency check, dynamic WHERE-clause
construction, and JSONB round-trip are exactly the kind of logic a mock
would rubber-stamp without actually exercising. Every test uses a unique,
namespaced user_id and cleans up its own rows.
"""
import uuid

import pytest

from app.services.corrections import (
    apply_chat_prohibition, detect_prohibition, find_retracted_match,
    get_active_corrections, record_correction, record_food_log_retraction,
)


def _uid() -> str:
    return f"test-corrections-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def db():
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def user_id():
    uid = _uid()
    yield uid


@pytest.fixture(autouse=True)
async def _cleanup(user_id):
    yield
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    async with get_async_session_factory()() as session:
        await session.execute(text("DELETE FROM correction WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()


class TestRecordAndReadCorrection:
    @pytest.mark.asyncio
    async def test_record_then_read_active(self, db, user_id):
        rec = await record_correction(
            db, user_id, correction_type="factual_correction",
            subject="person:Everett", predicate="relationship_to_david",
            old_value="brother", new_value="son", source_turn="Everett is my son, not my brother",
        )
        await db.commit()
        assert rec["subject"] == "person:Everett"

        active = await get_active_corrections(db, user_id, subject="person:Everett")
        assert len(active) == 1
        assert active[0]["new_value"] == "son"
        assert active[0]["explicit"] is True

    @pytest.mark.asyncio
    async def test_unknown_correction_type_raises(self, db, user_id):
        with pytest.raises(ValueError):
            await record_correction(
                db, user_id, correction_type="not_a_real_type", subject="x", new_value="y",
            )

    @pytest.mark.asyncio
    async def test_idempotent_repeat_does_not_duplicate(self, db, user_id):
        await record_correction(
            db, user_id, correction_type="preference", subject="food:cilantro",
            new_value="dislikes", source_turn="I hate cilantro",
        )
        await db.commit()
        await record_correction(
            db, user_id, correction_type="preference", subject="food:cilantro",
            new_value="dislikes", source_turn="I hate cilantro, seriously",
        )
        await db.commit()

        active = await get_active_corrections(db, user_id, subject="food:cilantro")
        assert len(active) == 1

    @pytest.mark.asyncio
    async def test_subject_prefix_matches_a_family(self, db, user_id):
        await record_correction(db, user_id, correction_type="event_attendance",
                                 subject="calendar_event:abc", new_value="not_attending")
        await record_correction(db, user_id, correction_type="event_attendance",
                                 subject="calendar_event:def", new_value="not_attending")
        await db.commit()

        active = await get_active_corrections(db, user_id, subject_prefix="calendar_event:")
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_expired_correction_is_not_active(self, db, user_id):
        from datetime import datetime, timedelta, timezone
        await record_correction(
            db, user_id, correction_type="temporary_exception", subject="reminder:gym",
            new_value="skip", scope="this_instance",
            effective_until=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await db.commit()

        active = await get_active_corrections(db, user_id, subject="reminder:gym")
        assert active == []


class TestFindRetractedMatch:
    @pytest.mark.asyncio
    async def test_matching_description_is_found(self, db, user_id):
        await record_food_log_retraction(db, user_id, "log-1", "dinner: beef taco pasta salad")
        await db.commit()

        match = await find_retracted_match(db, user_id, "beef taco pasta salad with extra cheese")
        assert match is not None
        assert match["subject"] == "food_log:log-1"

    @pytest.mark.asyncio
    async def test_unrelated_description_is_not_found(self, db, user_id):
        await record_food_log_retraction(db, user_id, "log-1", "dinner: beef taco pasta salad")
        await db.commit()

        match = await find_retracted_match(db, user_id, "grilled salmon and quinoa")
        assert match is None

    @pytest.mark.asyncio
    async def test_no_retractions_returns_none(self, db, user_id):
        match = await find_retracted_match(db, user_id, "anything at all")
        assert match is None


class TestDetectProhibition:
    def test_dont_do_that_again_is_detected(self):
        assert detect_prohibition("Don't do that again") is not None

    def test_i_removed_it_is_detected(self):
        hint = detect_prohibition("I removed it. Don't do that.")
        assert hint is not None
        assert hint["food_context"] is False

    def test_food_context_is_flagged(self):
        hint = detect_prohibition("Don't log that meal again")
        assert hint is not None
        assert hint["food_context"] is True

    def test_unrelated_message_is_not_detected(self):
        assert detect_prohibition("What's the weather like today?") is None

    def test_empty_message_is_not_detected(self):
        assert detect_prohibition("") is None


class TestApplyChatProhibition:
    @pytest.mark.asyncio
    async def test_non_food_prohibition_is_ignored(self, db, user_id):
        # "don't do that again" with no food context and no specific
        # referent — nothing safe to attach it to.
        result = await apply_chat_prohibition(db, user_id, "Don't do that again")
        assert result is None

    @pytest.mark.asyncio
    async def test_food_prohibition_upgrades_recent_retraction(self, db, user_id):
        rec = await record_food_log_retraction(db, user_id, "log-1", "dinner: taco pasta salad")
        await db.commit()
        assert rec["explicit"] is False

        result = await apply_chat_prohibition(db, user_id, "I removed it. Don't log that again.")
        await db.commit()

        assert result is not None
        assert result["subject"] == "food_log:log-1"
        assert result["explicit"] is True
        assert "Don't log that again" in result["source_turn"]

    @pytest.mark.asyncio
    async def test_food_prohibition_with_no_recent_retraction_is_recorded_unscoped(self, db, user_id):
        result = await apply_chat_prohibition(db, user_id, "Don't log that meal again")
        await db.commit()

        assert result is not None
        assert result["subject"] == "food_logging:unscoped"
        assert result["scope"] == "this_instance"

    @pytest.mark.asyncio
    async def test_never_bans_the_tool_outright(self, db, user_id):
        """The core correctness bar for this module: no amount of chat text
        alone should produce a permanent, tool-wide prohibition."""
        for _ in range(3):
            await apply_chat_prohibition(db, user_id, "Don't log that meal again")
        await db.commit()

        active = await get_active_corrections(db, user_id, correction_type="prohibition")
        assert all(a["scope"] != "permanent" for a in active)
        assert all(not a["subject"].startswith("tool:") for a in active)
