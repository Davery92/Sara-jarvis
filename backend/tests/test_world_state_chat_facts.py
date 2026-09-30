"""render_world_state_core's conversation_mode gating — personal-conversation
remediation plan (2026-09-23), step 2.

The evidence table's failures trace straight to this function: "Good
evening" got a completed-workout callback plus a day recap, and the family-
emergency turn got proposed email/SSL/ACORD work — the commitment and email
lines below. workout/location/calendar stay; they read as situational
awareness, not a task queue or a health readout, and the plan explicitly
allows "at most one relevant personal callback" on a greeting.

Each `_<domain>_line` helper is monkeypatched directly rather than faking a
SQLAlchemy `Session` — the module already tests its own DB wiring nowhere
(no existing test file), and re-deriving the ORM query shape here would test
mocks, not the gating logic this file exists to cover.
"""
import pytest

from app.services.world_state import chat_facts


@pytest.fixture(autouse=True)
def _stub_lines(monkeypatch):
    monkeypatch.setattr(chat_facts, "_workout_line", lambda db, uid: "Last workout: Push Day — completed 2h ago.")
    monkeypatch.setattr(chat_facts, "_location_line", lambda db, uid: "David is at Home (arrived 10m ago).")
    monkeypatch.setattr(chat_facts, "_calendar_line", lambda db, uid: None)
    monkeypatch.setattr(chat_facts, "_commitment_line", lambda db, uid: "Next due: File ACORD form — tomorrow 9am.")
    monkeypatch.setattr(chat_facts, "_email_line", lambda db, uid: "3 emails need a reply, most recent: SSL renewal.")
    monkeypatch.setattr(chat_facts, "_health_line", lambda db, uid: "Health data synced 10m ago: latest hrv 32.")


class TestUnconditionalDefault:
    def test_none_mode_keeps_every_line(self):
        text = chat_facts.render_world_state_core(db=object(), user_id="u1")
        assert "Push Day" in text
        assert "ACORD" in text
        assert "SSL renewal" in text
        assert "hrv 32" in text

    def test_action_mode_keeps_every_line(self):
        text = chat_facts.render_world_state_core(db=object(), user_id="u1", conversation_mode="action")
        assert "ACORD" in text
        assert "SSL renewal" in text
        assert "hrv 32" in text

    def test_mixed_mode_keeps_every_line(self):
        text = chat_facts.render_world_state_core(db=object(), user_id="u1", conversation_mode="mixed")
        assert "ACORD" in text
        assert "SSL renewal" in text


class TestAmbientSuppression:
    @pytest.mark.parametrize("mode", ["social", "personal_vulnerable"])
    def test_task_and_health_lines_dropped(self, mode):
        text = chat_facts.render_world_state_core(db=object(), user_id="u1", conversation_mode=mode)
        assert "ACORD" not in text
        assert "SSL renewal" not in text
        assert "hrv 32" not in text

    @pytest.mark.parametrize("mode", ["social", "personal_vulnerable"])
    def test_situational_lines_survive(self, mode):
        text = chat_facts.render_world_state_core(db=object(), user_id="u1", conversation_mode=mode)
        assert "Push Day" in text
        assert "Home" in text

    def test_empty_string_when_only_suppressed_lines_have_content(self, monkeypatch):
        monkeypatch.setattr(chat_facts, "_workout_line", lambda db, uid: None)
        monkeypatch.setattr(chat_facts, "_location_line", lambda db, uid: None)
        text = chat_facts.render_world_state_core(db=object(), user_id="u1", conversation_mode="social")
        assert text == ""
