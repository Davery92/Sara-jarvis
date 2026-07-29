"""
Tests for the actual remaining Arc 3.1 work (David's 2026-07-29 ruling):
"wake reasons shape the context and budget of one mind — they never select
different cognitions." Two pieces:

(a) wake_reason shapes context/budget *within* the one `ambient_turn` call —
    a description line threaded into the deliberation prompt, and `deep`
    derived from `wake_reason` when not passed explicitly (one source of
    truth for budget instead of two independently-passed params).
(b) an event pathway so deterministic sense jobs (anticipation, the weekly
    interoception self-audit) feed the kernel via events/salience promotion,
    not a new ambient_turn dispatch branch. The job bodies stay
    deterministic; only their *result* becomes an event.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import kernel
from app.services.deliberation_prompt import _describe_wake_reason, build_deliberation_prompt
from app.services.event_bus import EventType
from app.services.salience import salience_scorer


class TestWakeReasonContextShaping:
    def test_known_reason_produces_a_line(self):
        line = _describe_wake_reason("sleep_pressure")
        assert line.startswith("You're thinking right now because:")
        assert "safety-net" in line

    def test_unknown_or_missing_reason_produces_nothing(self):
        assert _describe_wake_reason(None) == ""
        assert _describe_wake_reason("") == ""
        assert _describe_wake_reason("not_a_real_reason") == ""

    def test_wake_reason_appears_in_the_built_prompt(self):
        memory = MagicMock()
        memory.rhythm_summary = None
        memory.activity_state = "available"
        memory.activity_confidence = 0.8
        memory.hours_since_last_chat = 1.0
        memory.hours_since_last_meal = 2.0
        memory.hours_since_app_activity = 1.0
        memory.next_event_minutes_away = None
        memory.sara_last_deliberation_at = None
        memory.last_heartbeat_handoff = None
        memory.sara_focus = None
        memory.sara_curiosities = []
        memory.observation_count = 0

        with patch("app.services.deliberation_prompt._format_memory_whiteboard", return_value="whiteboard"), \
             patch("app.services.deliberation_prompt._format_daemon_awareness", return_value=""):
            _, user_msg = build_deliberation_prompt(
                memory=memory, observations=[], wake_reason="scheduled_anchor",
            )

        assert "your twice-daily deep review" in user_msg

    def test_no_wake_reason_omits_the_line_entirely(self):
        memory = MagicMock()
        memory.rhythm_summary = None
        with patch("app.services.deliberation_prompt._format_memory_whiteboard", return_value="whiteboard"), \
             patch("app.services.deliberation_prompt._format_daemon_awareness", return_value=""):
            _, user_msg = build_deliberation_prompt(memory=memory, observations=[])

        assert "You're thinking right now because" not in user_msg


class TestBudgetDerivedFromWakeReason:
    @pytest.mark.asyncio
    async def test_scheduled_anchor_defaults_to_deep_when_not_passed(self):
        mock_ambient_turn_result = {"status": "completed", "notifications": 0, "home_actions": 0,
                                     "observations_consumed": 0}
        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        with patch("app.services.autonomy.coordination.get_coordinator") as mock_get_coord, \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)), \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value={"notifications_sent": 0, "home_actions_executed": 0,
                                                "observations_consumed": 0})):
            mock_coordinator = MagicMock()
            mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
            mock_coordinator.release_exclusive = AsyncMock()
            mock_get_coord.return_value = mock_coordinator

            await kernel.ambient_turn("user-1", wake_reason=kernel.WakeReason.SCHEDULED_ANCHOR, force=True)

        mock_engine.run.assert_awaited_once_with("user-1", deep=True, wake_reason="scheduled_anchor")

    @pytest.mark.asyncio
    async def test_promoted_event_defaults_to_shallow_when_not_passed(self):
        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        with patch("app.services.autonomy.coordination.get_coordinator") as mock_get_coord, \
             patch("app.services.salience.salience_scorer.should_deliberate", new=AsyncMock(return_value=True)), \
             patch("app.services.reflex.reflex_triage", new=AsyncMock(return_value="think")), \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value={"notifications_sent": 0, "home_actions_executed": 0,
                                                "observations_consumed": 0})):
            mock_coordinator = MagicMock()
            mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
            mock_coordinator.release_exclusive = AsyncMock()
            mock_get_coord.return_value = mock_coordinator

            await kernel.ambient_turn("user-1", wake_reason=kernel.WakeReason.PROMOTED_EVENT)

        mock_engine.run.assert_awaited_once_with("user-1", deep=False, wake_reason="promoted_event")

    @pytest.mark.asyncio
    async def test_explicit_deep_always_wins_over_the_derived_default(self):
        mock_result = MagicMock(thought="", duration_seconds=1.0)
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=mock_result)

        with patch("app.services.autonomy.coordination.get_coordinator") as mock_get_coord, \
             patch("app.services.deliberation.deliberation_engine", mock_engine), \
             patch("app.services.deliberation_gate.process_deliberation_result",
                   new=AsyncMock(return_value={"notifications_sent": 0, "home_actions_executed": 0,
                                                "observations_consumed": 0})):
            mock_coordinator = MagicMock()
            mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
            mock_coordinator.release_exclusive = AsyncMock()
            mock_get_coord.return_value = mock_coordinator

            # SLEEP_PRESSURE would normally derive deep=False; force it True.
            await kernel.ambient_turn(
                "user-1", wake_reason=kernel.WakeReason.SLEEP_PRESSURE, deep=True, force=True,
            )

        mock_engine.run.assert_awaited_once_with("user-1", deep=True, wake_reason="sleep_pressure")


class TestAnticipationEventPathway:
    @pytest.mark.asyncio
    async def test_anticipation_publishes_event_with_prep_summary(self):
        from app.tasks import autonomy

        fake_prep = MagicMock()
        fake_prep.prep_type.value = "calendar_review"

        mock_service = MagicMock()
        mock_service.run_morning_anticipation = AsyncMock(return_value=[fake_prep])

        mock_db_ctx = MagicMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_coordinator = MagicMock()
        mock_coordinator.acquire_exclusive = AsyncMock(return_value=True)
        mock_coordinator.release_exclusive = AsyncMock()

        mock_publish = AsyncMock()

        with patch("app.services.autonomy.coordination.get_coordinator", return_value=mock_coordinator), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_db_ctx), \
             patch("app.services.autonomy.anticipation.get_anticipation_service", new=AsyncMock(return_value=mock_service)), \
             patch("app.services.event_bus.event_bus.publish", mock_publish):

            await autonomy._anticipation_async("morning")

        mock_publish.assert_awaited_once()
        published = mock_publish.call_args[0][0]
        assert published.event_type == EventType.ANTICIPATION_COMPLETED
        assert published.payload["time_of_day"] == "morning"
        assert published.payload["prep_count"] == 1
        assert published.payload["prep_types"] == ["calendar_review"]


class TestSelfAuditEventPathway:
    @pytest.mark.asyncio
    async def test_self_audit_publishes_event_with_failing_count(self):
        from app.tasks import interoception

        mock_row = MagicMock()
        mock_row.scalar.return_value = 0
        mock_row.mappings.return_value.first.return_value = {"uf": 0, "it": 0}
        mock_row.first.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_row)
        mock_db.commit = AsyncMock()

        mock_db_ctx = MagicMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        fake_failing = [{"task_name": "app.tasks.foo.bar"}]
        mock_publish = AsyncMock()

        with patch("app.db.session.get_async_session_factory", return_value=lambda: mock_db_ctx), \
             patch("app.services.diagnostics_service.get_failing_tasks", new=AsyncMock(return_value=fake_failing)), \
             patch("app.services.diagnostics_service.record_system_event", new=AsyncMock()), \
             patch("app.services.event_bus.event_bus.publish", mock_publish):

            result = await interoception._weekly_self_audit_async()

        assert result["failing"] == 1
        mock_publish.assert_awaited_once()
        published = mock_publish.call_args[0][0]
        assert published.event_type == EventType.SELF_AUDIT_COMPLETED
        assert published.payload["failing_count"] == 1


class TestSenseEventsAreObservable:
    """The floor guarantees: a sense event always lands in the observation
    log (never silently dropped below the 0.3 log floor), and self-audit
    escalates when it's actually surfacing failing jobs."""

    def test_anticipation_clears_the_observation_floor_even_with_nothing_to_prepare(self):
        from app.services.event_bus import Event

        event = Event(event_type=EventType.ANTICIPATION_COMPLETED, user_id="test-user", source="morning_anticipation",
                       payload={"time_of_day": "morning", "prep_count": 0, "prep_types": []})
        score = salience_scorer._apply_category_floors(event, 0.0)
        assert score >= 0.3

    def test_self_audit_with_failures_scores_higher_than_without(self):
        from app.services.event_bus import Event

        clean = Event(event_type=EventType.SELF_AUDIT_COMPLETED, user_id="test-user", source="weekly_self_audit",
                       payload={"failing_count": 0, "muted_count": 0})
        degraded = Event(event_type=EventType.SELF_AUDIT_COMPLETED, user_id="test-user", source="weekly_self_audit",
                          payload={"failing_count": 3, "muted_count": 0})

        clean_score = salience_scorer._apply_category_floors(clean, 0.0)
        degraded_score = salience_scorer._apply_category_floors(degraded, 0.0)
        assert degraded_score > clean_score
        assert clean_score >= 0.3  # still observable

    def test_salience_subscriber_subscribes_to_both_sense_events(self):
        from app.services.salience_subscriber import SalienceSubscriber

        sub = SalienceSubscriber()
        assert EventType.ANTICIPATION_COMPLETED in sub.subscribed_events
        assert EventType.SELF_AUDIT_COMPLETED in sub.subscribed_events

    def test_describe_and_categorize_do_not_raise(self):
        from app.services.event_bus import Event

        for etype, payload in (
            (EventType.ANTICIPATION_COMPLETED, {"time_of_day": "evening", "prep_types": ["tomorrow_prep"]}),
            (EventType.SELF_AUDIT_COMPLETED, {"failing_count": 2, "muted_count": 1}),
        ):
            event = Event(event_type=etype, user_id="test-user", source="test", payload=payload)
            assert salience_scorer.describe_event(event)
            assert salience_scorer.categorize_event(event)
