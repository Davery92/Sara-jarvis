"""
Tests for the Daily Log / Diary pipeline (DAILY_LOG_DIARY_PLAN_2026_08_25).

Two things worth pinning down, both pure functions:

1. `day_bounds()` — the twelve replay collectors read a mix of timestamptz,
   naive-UTC and naive-ET columns. Getting one ET calendar day into all three
   conventions (and across the DST boundary) is the whole Phase 1 fix.
2. `render_facts()` / `_is_thin_day()` — the model only ever sees what these
   produce, so an empty section leaking through is a hallucination invitation.
"""

from datetime import date, datetime

from app.services.day_replay_builder import day_bounds, utc_naive_to_et_naive
from app.services.daily_log_service import daily_log_service


class TestDayBounds:
    def test_edt_day_is_four_hours_off_utc(self):
        b = day_bounds(date(2026, 8, 24))
        assert b.et_naive_start == datetime(2026, 8, 24, 0, 0)
        # Midnight ET on an EDT date is 04:00 UTC the same day...
        assert b.utc_naive_start == datetime(2026, 8, 24, 4, 0)
        # ...and the day ends just before 04:00 UTC the NEXT day. This is the
        # bit the old naive datetime.combine() pair got wrong: an 11 PM chat
        # (03:00 UTC tomorrow) fell outside the window and landed on the
        # following day's replay.
        assert b.utc_naive_end.date() == date(2026, 8, 25)
        assert b.utc_naive_end.hour == 3

    def test_est_day_is_five_hours_off_utc(self):
        b = day_bounds(date(2026, 1, 15))
        assert b.utc_naive_start == datetime(2026, 1, 15, 5, 0)
        assert b.utc_naive_end.date() == date(2026, 1, 16)
        assert b.utc_naive_end.hour == 4

    def test_aware_bounds_are_eastern(self):
        b = day_bounds(date(2026, 8, 24))
        assert b.aware_start.tzinfo is not None
        assert b.aware_start.utcoffset().total_seconds() == -4 * 3600
        assert b.aware_start.hour == 0
        assert b.aware_end.hour == 23

    def test_late_evening_chat_falls_inside_its_own_et_day(self):
        # An 11 PM ET conversation is stored as 03:00 UTC the next calendar day.
        stored_naive_utc = datetime(2026, 8, 25, 3, 5)
        b = day_bounds(date(2026, 8, 24))
        assert b.utc_naive_start <= stored_naive_utc <= b.utc_naive_end
        assert utc_naive_to_et_naive(stored_naive_utc).date() == date(2026, 8, 24)

    def test_next_day_bounds_exclude_it(self):
        stored_naive_utc = datetime(2026, 8, 25, 3, 5)
        b = day_bounds(date(2026, 8, 25))
        assert not (b.utc_naive_start <= stored_naive_utc <= b.utc_naive_end)


class TestUtcNaiveToEtNaive:
    def test_converts_and_strips_tzinfo(self):
        got = utc_naive_to_et_naive(datetime(2026, 8, 25, 14, 45))
        assert got == datetime(2026, 8, 25, 10, 45)
        assert got.tzinfo is None

    def test_none_passes_through(self):
        assert utc_naive_to_et_naive(None) is None


def _empty_payload(**overrides):
    payload = {
        "date": "2026-08-24",
        "weekday": "Monday",
        "chat": {"summaries": None, "sessions": []},
        "fitness": {"workouts": [], "lifting": {}, "cardio": [], "activity": {}},
        "nutrition": {},
        "recovery": {},
        "calendar": [],
        "tasks": {},
        "learning": [],
        "notes": [],
        "sara": {},
        "misc": {},
    }
    payload.update(overrides)
    return payload


class TestThinDayDetection:
    def test_no_evidence_is_thin(self):
        assert daily_log_service._is_thin_day(_empty_payload()) is True

    def test_sara_notes_alone_are_still_thin(self):
        # Sara's own journal is not evidence of David's day.
        payload = _empty_payload(sara={"journal": [{"time": "1:00 AM", "content": "..."}]})
        assert daily_log_service._is_thin_day(payload) is True

    def test_someone_elses_calendar_event_is_still_thin(self):
        payload = _empty_payload(calendar=[
            {"title": "Kid's dentist", "owner": "family", "is_davids": False},
        ])
        assert daily_log_service._is_thin_day(payload) is True

    def test_his_own_calendar_event_is_not_thin(self):
        payload = _empty_payload(calendar=[
            {"title": "Standup", "owner": "self", "is_davids": True},
        ])
        assert daily_log_service._is_thin_day(payload) is False

    def test_a_workout_is_not_thin(self):
        payload = _empty_payload(fitness={
            "workouts": [{"time": "6:00 AM", "type": "Push", "duration_minutes": 45}],
            "lifting": {}, "cardio": [], "activity": {},
        })
        assert daily_log_service._is_thin_day(payload) is False


class TestRenderFacts:
    def test_empty_payload_renders_no_sections(self):
        facts = daily_log_service.render_facts(_empty_payload())
        assert facts == "(No recorded activity for this day.)"
        assert "##" not in facts

    def test_empty_sections_are_omitted(self):
        payload = _empty_payload(nutrition={
            "meals": [{"time": "9:10 AM", "meal": "breakfast",
                       "description": "Eggs", "calories": 300, "protein": 24}],
            "totals": {"calories": 300, "protein": 24, "carbs": 2, "fat": 20},
        })
        facts = daily_log_service.render_facts(payload)
        assert "## Nutrition" in facts
        # Nothing else was recorded, so nothing else may appear.
        assert "## Calendar" not in facts
        assert "## Training & movement" not in facts
        assert "## Conversations" not in facts

    def test_calendar_ownership_is_flagged_for_the_model(self):
        payload = _empty_payload(calendar=[
            {"time": "1:00 PM", "title": "Dentist", "location": None,
             "duration_minutes": 30, "owner": "family", "is_davids": False},
        ])
        facts = daily_log_service.render_facts(payload)
        assert "NOT David's" in facts

    def test_totals_are_precomputed_not_left_to_the_model(self):
        payload = _empty_payload(nutrition={
            "meals": [{"time": "9:10 AM", "meal": "breakfast",
                       "description": "Eggs", "calories": 300, "protein": 24}],
            "totals": {"calories": 1939, "protein": 187, "carbs": 110, "fat": 79},
        })
        facts = daily_log_service.render_facts(payload)
        assert "1,939 kcal" in facts
        assert "187g protein" in facts

    def test_oversized_sheet_drops_low_value_sections_and_says_so(self):
        payload = _empty_payload(
            notes=[{"title": "N" * 2000, "folder": "F", "action": "created",
                    "time": "9:00 AM"} for _ in range(12)],
            misc={"automations": [{"name": "A" * 20000, "runs": 1, "successful": 1}]},
        )
        facts = daily_log_service.render_facts(payload)
        assert "Fact sheet trimmed for length" in facts
        assert "Background" in facts  # names what it dropped
        assert "## Notes" in facts    # keeps the higher-value section

    def test_a_single_oversized_section_is_truncated_not_dropped(self):
        payload = _empty_payload(
            misc={"automations": [{"name": "A" * 60000, "runs": 1, "successful": 1}]},
        )
        facts = daily_log_service.render_facts(payload)
        assert "## Background" in facts
        assert "(truncated)" in facts


class TestJournalDedupe:
    def test_night_watch_repetition_is_collapsed(self):
        entries = [
            {"time": f"12:{n:02d} AM", "type": "deliberation", "mood": "protective",
             "content": f"The house is quiet and secure. Sweep {n}."}
            for n in (0, 6, 12, 18, 24, 30)
        ]
        kept = daily_log_service._dedupe_journal(entries)
        # Same 60-char prefix on all six → one survives, and the deliberation
        # cap would hold it to two regardless.
        assert len(kept) <= 2

    def test_distinct_entries_survive(self):
        entries = [
            {"time": "9:00 AM", "type": "weekly_review", "mood": None, "content": "Week in review."},
            {"time": "1:00 PM", "type": "curiosity", "mood": None, "content": "Wondering about X."},
        ]
        assert len(daily_log_service._dedupe_journal(entries)) == 2
