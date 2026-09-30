"""End-to-end proof for email: real writer -> coordinator -> reducer
pipeline, into the actual chat payload. Uses the exact payload shape
tasks/email_sync.py's real `email.analyzed` producer emits (action_required
drives the follow_up thread; email_thread_key keys it on the conversation,
not the message, so a reply-chain is one open thread, not one per message)
— email analysis itself is an LLM-driven background task, so this proves
the reducer/snapshot/payload contract against the real producer's payload
shape rather than invoking the classifier.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_email_world_state_integration_pg.py
"""
import os
import uuid

import pytest
from sqlalchemy import text

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
    uid = f"test-email-{uuid.uuid4()}"
    yield uid
    pg.rollback()
    pg.execute(text("""
        DELETE FROM world_event_processing
        WHERE event_id IN (SELECT event_id FROM world_event WHERE user_id = :u)
    """), {"u": uid})
    for table in ("world_event", "world_thread", "world_fact", "world_snapshot"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.commit()


def _emit_analyzed(pg, user_id, email_id, conversation_id, *, subject, action_required, dedupe_key):
    from app.services.world_state.writer import append_world_event
    from app.services.world_state.coordinator import process_one

    row = append_world_event(
        pg, user_id=user_id, kind="email.analyzed", source="email_analyzer",
        source_ref=f"email:{email_id}", aggregate_type="email", aggregate_id=email_id,
        correlation_id=str(conversation_id or email_id), dedupe_key=dedupe_key,
        payload={
            "email_id": email_id, "conversation_id": conversation_id, "subject": subject,
            "sender_email": "laura@example.com", "sender_name": "Laura Weippert",
            "category": "scheduling", "importance_score": 0.7, "summary": subject,
            "action_required": action_required, "has_meeting": False, "is_read": False,
            "actionability": 0.9 if action_required else 0.0,
            "urgency": 0.7 if action_required else 0.0,
        },
    )
    pg.commit()
    assert row is not None
    return process_one(pg, row.event_id)


@requires_pg
class TestEmailProducer:
    def test_action_required_email_reaches_the_snapshot(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core

        conv_id = str(uuid.uuid4())
        _emit_analyzed(
            pg, user_id, str(uuid.uuid4()), conv_id,
            subject="RE: Connect with the Dave's", action_required=True,
            dedupe_key=f"email-analyzed:{conv_id}:1",
        )

        core = render_world_state_core(pg, user_id)
        assert "1 email needs a reply" in core
        assert "Connect with the Dave's" in core

    def test_a_five_message_thread_is_one_open_thread_not_five(self, pg, user_id):
        """email_thread_key keys on conversation_id, not message id."""
        from app.models.world_model import WorldThread
        from sqlalchemy import select

        conv_id = str(uuid.uuid4())
        for i in range(5):
            _emit_analyzed(
                pg, user_id, str(uuid.uuid4()), conv_id,
                subject="RE: Connect with the Dave's", action_required=True,
                dedupe_key=f"email-analyzed:{conv_id}:{i}",
            )

        threads = pg.execute(select(WorldThread).where(
            WorldThread.user_id == user_id, WorldThread.thread_key == f"email:{conv_id}",
        )).scalars().all()
        assert len(threads) == 1

        from app.services.world_state.chat_facts import render_world_state_core
        core = render_world_state_core(pg, user_id)
        assert "1 email needs a reply" in core  # one thread, not five

    def test_a_non_action_email_does_not_appear_as_needing_a_reply(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core

        conv_id = str(uuid.uuid4())
        _emit_analyzed(
            pg, user_id, str(uuid.uuid4()), conv_id,
            subject="Thank you!", action_required=False,
            dedupe_key=f"email-analyzed:{conv_id}:ack",
        )

        core = render_world_state_core(pg, user_id)
        assert "needs a reply" not in core

    def test_the_reply_needed_fact_reaches_the_actual_chat_payload(self, pg, user_id):
        from app.services.world_state.chat_facts import render_world_state_core
        from app.services.chat_assembly import assemble_local_provider_messages
        from app.schemas.chat import ChatMessage

        conv_id = str(uuid.uuid4())
        _emit_analyzed(
            pg, user_id, str(uuid.uuid4()), conv_id,
            subject="Can we move this call to tomorrow?", action_required=True,
            dedupe_key=f"email-analyzed:{conv_id}:1",
        )
        core = render_world_state_core(pg, user_id)

        stable = "You are Sara."
        assembly = assemble_local_provider_messages(
            full_sys=stable + "\n\n" + ("z" * 6000),
            stable_system_prompt=stable,
            conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="anything I need to handle?")],
            dialogue_block="", world_state_core=core, world_brief="",
            datetime_line="It's Thursday, 2pm ET.", live_context_char_budget=4500,
        )
        user_msgs = [m for m in assembly["all_messages"] if m.role == "user"]
        content = user_msgs[-1].content
        text_ = "\n".join(p.get("text", "") for p in content) if isinstance(content, list) else content
        assert "move this call to tomorrow" in text_
