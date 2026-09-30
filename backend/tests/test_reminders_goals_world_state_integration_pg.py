"""End-to-end proof for reminders and goals — living-world-context plan
§1's explicit demand: 'complete email, reminders, goals, and health
coverage through the maintained snapshot and actual chat payload. Generic
infrastructure tests don't replace domain-specific verification.'

Drives the REAL producer entry points (RemindersCreateTool, the reminders
API route, GoalManager) — not a hand-crafted event — because those
producers were the actual gap this session found and fixed: reminders and
goals were fully modeled in the catalog/reducer but had no live producer
at all (goal_manager's old event_bus.publish() call passed a plain dict,
which record_legacy_event can't read, and only fired when an event_bus
instance was wired in, which it never was).

Then proves the fact reaches the ACTUAL outgoing chat payload via
assemble_local_provider_messages — not just the allocator with a synthetic
string.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_reminders_goals_world_state_integration_pg.py
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the PostgreSQL dev database (run inside the backend container)"
)


@pytest.fixture(autouse=True)
def _world_events_enabled(monkeypatch):
    monkeypatch.setenv("WORLD_EVENTS_ENABLED", "true")
    from app.celery_app import celery_app
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def user_id(pg):
    uid = f"test-commit-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM reminder WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM goal WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _process_event_for(pg, user_id, dedupe_key):
    from app.services.world_state.coordinator import process_one
    from app.models.world_model import WorldEvent
    event = pg.execute(select(WorldEvent).where(
        WorldEvent.user_id == user_id, WorldEvent.dedupe_key == dedupe_key,
    )).scalar_one()
    return process_one(pg, event.event_id)


@requires_pg
@pytest.mark.asyncio
class TestReminderProducer:
    async def test_creating_a_reminder_via_the_chat_tool_reaches_the_snapshot(self, pg, user_id):
        from app.tools.reminders import RemindersCreateTool
        from app.services.world_state.chat_facts import render_world_state_core

        due = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        result = await RemindersCreateTool().execute(
            user_id=user_id, title="Call the vet", reminder_time=due, confirm_time=True,
        )
        assert result.success, result.message
        reminder_id = result.data["reminder_id"]

        _process_event_for(pg, user_id, f"reminder-created:{reminder_id}")

        core = render_world_state_core(pg, user_id)
        assert "Next due: Call the vet" in core

    async def test_the_commitment_reaches_the_actual_outgoing_chat_payload(self, pg, user_id):
        """Domain-specific, not generic: the real reminder, through the real
        producer and real reducer, inside the actual assembled message
        list — not a synthetic world_state_core string handed to the
        allocator directly."""
        from app.tools.reminders import RemindersCreateTool
        from app.services.world_state.chat_facts import render_world_state_core
        from app.services.chat_assembly import assemble_local_provider_messages
        from app.schemas.chat import ChatMessage

        due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = await RemindersCreateTool().execute(
            user_id=user_id, title="Submit the expense report", reminder_time=due, confirm_time=True,
        )
        assert result.success
        reminder_id = result.data["reminder_id"]
        _process_event_for(pg, user_id, f"reminder-created:{reminder_id}")

        core = render_world_state_core(pg, user_id)
        stable = "You are Sara."
        assembly = assemble_local_provider_messages(
            full_sys=stable + "\n\n" + ("z" * 6000),  # crowd out the budget, as in production
            stable_system_prompt=stable,
            conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="what's on my plate")],
            dialogue_block="",
            world_state_core=core,
            world_brief="",
            datetime_line="It's Thursday, 2pm ET.",
            live_context_char_budget=4500,
        )
        user_msgs = [m for m in assembly["all_messages"] if m.role == "user"]
        content = user_msgs[-1].content
        text_ = "\n".join(p.get("text", "") for p in content) if isinstance(content, list) else content
        assert "Submit the expense report" in text_

    async def test_completing_a_reminder_via_the_api_route_closes_the_thread(self, pg, user_id):
        from app.tools.reminders import RemindersCreateTool
        from app.routes.reminders import complete_reminder
        from types import SimpleNamespace
        from app.models.world_model import WorldThread

        due = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        created = await RemindersCreateTool().execute(
            user_id=user_id, title="Renew car registration", reminder_time=due, confirm_time=True,
        )
        reminder_id = created.data["reminder_id"]
        _process_event_for(pg, user_id, f"reminder-created:{reminder_id}")

        await complete_reminder(
            reminder_id=reminder_id, current_user=SimpleNamespace(id=user_id), db=pg,
        )
        _process_event_for(pg, user_id, f"reminder-completed:{reminder_id}")

        thread = pg.execute(select(WorldThread).where(
            WorldThread.user_id == user_id, WorldThread.thread_key == f"reminders:{reminder_id}",
        )).scalar_one()
        assert thread.status == "resolved"


@requires_pg
@pytest.mark.asyncio
class TestGoalProducer:
    async def test_creating_a_goal_reaches_the_snapshot_and_chat_payload(self, pg, user_id):
        from app.services.goal_manager import GoalManager, Goal
        from app.services.world_state.chat_facts import render_world_state_core
        from app.services.chat_assembly import assemble_local_provider_messages
        from app.schemas.chat import ChatMessage

        target_date = (datetime.now(timezone.utc) + timedelta(days=3)).date()
        goal = Goal(
            user_id=user_id, title="Finish the Q3 report", description=None,
            goal_type="project", target_value=None, current_value=None, unit=None,
            target_date=target_date, status="active", priority=5, metadata={},
        )
        manager = GoalManager(pg)  # no event_bus — exercises the direct-producer path
        goal_id = await manager.create_goal(goal)

        _process_event_for(pg, user_id, f"goal-created:{goal_id}")

        core = render_world_state_core(pg, user_id)
        assert "Next due: Finish the Q3 report" in core

        stable = "You are Sara."
        assembly = assemble_local_provider_messages(
            full_sys=stable + "\n\n" + ("z" * 6000),
            stable_system_prompt=stable,
            conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="what am I working on")],
            dialogue_block="", world_state_core=core, world_brief="",
            datetime_line="It's Thursday, 2pm ET.", live_context_char_budget=4500,
        )
        user_msgs = [m for m in assembly["all_messages"] if m.role == "user"]
        content = user_msgs[-1].content
        text_ = "\n".join(p.get("text", "") for p in content) if isinstance(content, list) else content
        assert "Finish the Q3 report" in text_
