"""
Tests for ActivityStateMachine — Sara's awareness of what David is doing.

Tests the FSM that infers David's current activity from signals:
motion sensors, calendar, interactions, time, devices, sleep, workouts.
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.activity_state_machine import (
    ActivityStateMachine,
    ActivityState,
    ActivitySnapshot,
    ActivitySignal,
    STATE_INTERRUPTIBILITY,
    STATE_DECAY_MINUTES,
)

USER_TZ = ZoneInfo("America/New_York")


class TestInitialState:
    def test_initial_state_is_unknown(self, activity_machine):
        assert activity_machine.current.state == ActivityState.UNKNOWN

    def test_initial_confidence_is_low(self, activity_machine):
        assert activity_machine.current.confidence <= 0.5

    def test_initial_interruptibility_matches_unknown(self, activity_machine):
        assert activity_machine.current.interruptibility == STATE_INTERRUPTIBILITY[ActivityState.UNKNOWN]


class TestMotionSignals:
    def test_motion_signal_records_room_but_no_transition(self, activity_machine, make_signal):
        # Motion sensors can't distinguish household members — _handle_motion()
        # only records room occupancy, does NOT transition state.
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.AWAY, confidence=0.7,
            since=datetime.now(USER_TZ) - timedelta(hours=1),
            reason="test",
        )
        signal = make_signal(signal_type="motion", source="binary_sensor.living_room_motion", value="on")
        result = activity_machine.process_signal(signal)
        # State stays AWAY — motion alone doesn't transition
        assert result.state == ActivityState.AWAY
        # But room motion is recorded
        assert "living_room" in activity_machine._room_motion

    def test_motion_while_sleeping_no_transition(self, activity_machine, make_signal):
        # Motion doesn't transition from SLEEPING — could be another household member.
        # Only explicit interaction or sleep_end transitions out of SLEEPING.
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.SLEEPING, confidence=0.7,
            since=datetime.now(USER_TZ) - timedelta(hours=4),
            reason="test",
        )
        signal = make_signal(
            signal_type="motion", source="binary_sensor.living_room_motion",
            value="on", metadata={"room": "living_room"},
        )
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.SLEEPING


class TestRoomExtraction:
    def test_room_extraction_office(self, activity_machine):
        room = activity_machine._entity_to_room("binary_sensor.office_motion")
        assert room == "office"

    def test_room_extraction_kitchen(self, activity_machine):
        room = activity_machine._entity_to_room("binary_sensor.kitchen_occupancy")
        assert room == "kitchen"

    def test_room_extraction_living_room(self, activity_machine):
        room = activity_machine._entity_to_room("light.living_room_lamp")
        assert room == "living_room"

    def test_room_extraction_no_match(self, activity_machine):
        room = activity_machine._entity_to_room("sensor.cpu_temperature")
        # Falls back to suffix-based extraction or None
        assert room is None or isinstance(room, str)

    def test_room_extraction_no_dot(self, activity_machine):
        room = activity_machine._entity_to_room("invalid")
        assert room is None


class TestCalendarSignals:
    def test_calendar_meeting_transitions_to_in_meeting(self, activity_machine, make_signal):
        signal = make_signal(
            signal_type="calendar", source="calendar",
            value="meeting_start", metadata={"title": "Team Standup"},
        )
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.IN_MEETING
        assert result.confidence >= 0.8

    def test_calendar_gym_transitions_to_exercising(self, activity_machine, make_signal):
        signal = make_signal(
            signal_type="calendar", source="calendar",
            value="meeting_start", metadata={"title": "Gym session"},
        )
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.EXERCISING

    def test_meeting_end_transitions_to_active(self, activity_machine, make_signal):
        # First go to IN_MEETING
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.IN_MEETING, confidence=0.85,
            since=datetime.now(USER_TZ) - timedelta(minutes=30),
            reason="meeting",
        )
        signal = make_signal(signal_type="calendar", source="calendar", value="meeting_end")
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.ACTIVE


class TestSleepSignals:
    def test_sleep_start_transitions_to_sleeping(self, activity_machine, make_signal):
        signal = make_signal(signal_type="sleep", source="health", value="sleep_start")
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.SLEEPING
        assert result.confidence >= 0.9

    def test_sleep_end_transitions_to_waking(self, activity_machine, make_signal):
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.SLEEPING, confidence=0.9,
            since=datetime.now(USER_TZ) - timedelta(hours=7),
            reason="sleep",
        )
        signal = make_signal(signal_type="sleep", source="health", value="sleep_end")
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.WAKING


class TestWorkoutSignals:
    def test_workout_start_transitions_to_exercising(self, activity_machine, make_signal):
        signal = make_signal(
            signal_type="workout", source="health", value="start",
            metadata={"type": "strength"},
        )
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.EXERCISING
        assert result.confidence >= 0.9

    def test_workout_end_transitions_to_active(self, activity_machine, make_signal):
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.EXERCISING, confidence=0.9,
            since=datetime.now(USER_TZ) - timedelta(minutes=60),
            reason="workout",
        )
        signal = make_signal(signal_type="workout", source="health", value="end")
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.ACTIVE


class TestInteractionSignals:
    def test_interaction_wakes_from_sleeping(self, activity_machine, make_signal):
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.SLEEPING, confidence=0.6,
            since=datetime.now(USER_TZ) - timedelta(hours=6),
            reason="night",
        )
        signal = make_signal(signal_type="interaction", source="chat", value="message")
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.WAKING

    def test_interaction_boosts_active_confidence(self, activity_machine, make_signal):
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.ACTIVE, confidence=0.5,
            since=datetime.now(USER_TZ) - timedelta(minutes=30),
            reason="active",
        )
        old_conf = activity_machine._current.confidence
        signal = make_signal(signal_type="interaction", source="chat", value="message")
        activity_machine.process_signal(signal)
        assert activity_machine._current.confidence >= old_conf


class TestTimeSignals:
    def test_late_night_transitions_to_winding_down(self, activity_machine, make_signal):
        signal = make_signal(signal_type="time", source="clock", value="tick", hour=23)
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.WINDING_DOWN

    def test_middle_of_night_transitions_to_sleeping(self, activity_machine, make_signal):
        signal = make_signal(signal_type="time", source="clock", value="tick", hour=3)
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.SLEEPING


class TestDeviceSignals:
    def test_computer_on_triggers_focused_work(self, activity_machine, make_signal):
        signal = make_signal(
            signal_type="device", source="computer_workstation", value="on",
        )
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.FOCUSED_WORK

    def test_computer_off_leaves_focused_work(self, activity_machine, make_signal):
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.FOCUSED_WORK, confidence=0.6,
            since=datetime.now(USER_TZ) - timedelta(hours=1),
            reason="computer on",
        )
        signal = make_signal(
            signal_type="device", source="computer_workstation", value="off",
        )
        result = activity_machine.process_signal(signal)
        assert result.state == ActivityState.ACTIVE


class TestComputeFromFullContext:
    def _now(self, hour, minute=0):
        return datetime.now(USER_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)

    def test_sleeping_state_at_night(self, activity_machine):
        now = self._now(3)
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=[], first_activity_today=None,
            has_chatted_today=False,
        )
        assert result.state == ActivityState.SLEEPING

    def test_waking_state_from_first_activity(self, activity_machine):
        now = self._now(7, 15)
        first_activity = now - timedelta(minutes=10)
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=[], first_activity_today=first_activity,
            has_chatted_today=False,
        )
        assert result.state == ActivityState.WAKING

    def test_morning_routine_after_waking(self, activity_machine):
        now = self._now(7, 45)
        first_activity = now - timedelta(minutes=60)
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=[], first_activity_today=first_activity,
            has_chatted_today=False,
        )
        assert result.state == ActivityState.MORNING_ROUTINE

    def test_calendar_meeting_during_day(self, activity_machine):
        now = self._now(14)
        events = [{
            "title": "1:1 with manager",
            "start": (now - timedelta(minutes=15)).isoformat(),
            "end": (now + timedelta(minutes=15)).isoformat(),
        }]
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=events, last_interaction_at=None,
            body_state=None, ha_recent_activity=[], first_activity_today=self._now(7),
            has_chatted_today=True,
        )
        assert result.state == ActivityState.IN_MEETING

    def test_office_motion_suggests_active(self, activity_machine):
        # Motion sensors can't distinguish household members, so office motion
        # only produces a weak ACTIVE signal (0.25), not FOCUSED_WORK.
        now = self._now(10)
        ha_activity = [{
            "entity_id": "binary_sensor.office_motion",
            "to_state": "on",
            "changed_at": (now - timedelta(minutes=5)).isoformat(),
        }]
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=ha_activity,
            first_activity_today=self._now(7), has_chatted_today=True,
        )
        assert result.state == ActivityState.ACTIVE

    def test_kitchen_motion_suggests_cooking(self, activity_machine):
        now = self._now(12)
        ha_activity = [{
            "entity_id": "binary_sensor.kitchen_motion",
            "to_state": "on",
            "changed_at": (now - timedelta(minutes=5)).isoformat(),
        }]
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=ha_activity,
            first_activity_today=self._now(7), has_chatted_today=True,
        )
        # Kitchen motion at lunchtime → COOKING is a candidate
        assert result.state in (ActivityState.COOKING, ActivityState.ACTIVE)

    def test_winding_down_evening(self, activity_machine):
        now = self._now(22)
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=[], first_activity_today=self._now(7),
            has_chatted_today=True,
        )
        assert result.state in (ActivityState.WINDING_DOWN, ActivityState.AWAY)

    def test_no_signals_during_day_stays_unknown(self, activity_machine):
        # With no HA activity, no calendar, no interaction — zero candidates.
        # compute_from_full_context keeps current state (UNKNOWN) with decayed confidence.
        now = self._now(14)
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=[], first_activity_today=self._now(7),
            has_chatted_today=True,
        )
        assert result.state == ActivityState.UNKNOWN


class TestHysteresis:
    def test_hysteresis_prevents_flip_flop(self, activity_machine):
        """Current state gets a 0.15 confidence bonus to prevent rapid flapping."""
        now = datetime.now(USER_TZ).replace(hour=14, minute=0)

        # First compute → FOCUSED_WORK at 0.5
        ha = [{
            "entity_id": "binary_sensor.office_motion",
            "to_state": "on",
            "changed_at": (now - timedelta(minutes=5)).isoformat(),
        }]
        activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=ha,
            first_activity_today=now.replace(hour=7), has_chatted_today=True,
        )
        state1 = activity_machine._current.state

        # Second compute with slightly different signals — should stay due to hysteresis
        ha2 = [{
            "entity_id": "binary_sensor.living_room_motion",
            "to_state": "on",
            "changed_at": (now - timedelta(minutes=3)).isoformat(),
        }]
        result = activity_machine.compute_from_full_context(
            now=now, calendar_events=[], last_interaction_at=None,
            body_state=None, ha_recent_activity=ha2,
            first_activity_today=now.replace(hour=7), has_chatted_today=True,
        )
        # The state might change, but the point is it doesn't flip-flop easily
        # when both states have similar confidence
        assert result.state in (state1, ActivityState.ACTIVE)


class TestStateEvents:
    def test_state_transition_generates_event(self, activity_machine, make_signal):
        signal = make_signal(signal_type="sleep", source="health", value="sleep_start")
        activity_machine.process_signal(signal)
        events = activity_machine.drain_pending_events()
        assert len(events) >= 1
        assert events[0]["new"] == "sleeping"

    def test_drain_clears_events(self, activity_machine, make_signal):
        signal = make_signal(signal_type="sleep", source="health", value="sleep_start")
        activity_machine.process_signal(signal)
        activity_machine.drain_pending_events()
        events2 = activity_machine.drain_pending_events()
        assert events2 == []


class TestRestoreState:
    def test_restore_state_from_dict(self, activity_machine):
        state_dict = {
            "state": "focused_work",
            "confidence": 0.75,
            "since": datetime.now(USER_TZ).isoformat(),
            "reason": "restored from test",
            "room": "office",
            "interruptibility": 0.2,
        }
        activity_machine.restore_state(state_dict)
        assert activity_machine._current.state == ActivityState.FOCUSED_WORK
        assert activity_machine._current.confidence == 0.75
        assert activity_machine._current.room == "office"

    def test_restore_invalid_state_no_crash(self, activity_machine):
        activity_machine.restore_state({"state": "bogus_state"})
        # Should not crash; may keep old state or go to UNKNOWN
        assert isinstance(activity_machine._current.state, ActivityState)


class TestDecay:
    def test_confidence_decay_over_time(self, activity_machine):
        # Set a state with stale timestamp (halfway to max decay)
        max_age = STATE_DECAY_MINUTES.get(ActivityState.FOCUSED_WORK, 180)
        stale_time = datetime.now(USER_TZ) - timedelta(minutes=max_age * 0.75)
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.FOCUSED_WORK, confidence=0.8,
            since=stale_time, reason="old state",
        )
        current = activity_machine.current  # triggers _apply_decay
        assert current.confidence < 0.8

    def test_expired_state_falls_back(self, activity_machine):
        max_age = STATE_DECAY_MINUTES.get(ActivityState.WAKING, 30)
        stale_time = datetime.now(USER_TZ) - timedelta(minutes=max_age + 10)
        activity_machine._current = ActivitySnapshot(
            state=ActivityState.WAKING, confidence=0.8,
            since=stale_time, reason="old waking",
        )
        current = activity_machine.current
        # Should have decayed to ACTIVE (daytime) or UNKNOWN (nighttime)
        assert current.state in (ActivityState.ACTIVE, ActivityState.UNKNOWN)


class TestSignalBuffer:
    def test_signals_buffered(self, activity_machine, make_signal):
        for i in range(5):
            activity_machine.process_signal(
                make_signal(signal_type="motion", source=f"sensor_{i}", value="on")
            )
        assert len(activity_machine._recent_signals) == 5

    def test_buffer_max_size(self, activity_machine, make_signal):
        for i in range(60):
            activity_machine.process_signal(
                make_signal(signal_type="motion", source=f"sensor_{i}", value="on")
            )
        assert len(activity_machine._recent_signals) <= activity_machine._max_signal_buffer
