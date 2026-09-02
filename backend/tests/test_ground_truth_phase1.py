"""Ground-truth Phase 1: Sara stops inventing obligations.

Replays the 2026-08-31 Laura Weippert sequence — an emailed reschedule request
with no time in it, a reply sent, and Sara's own assistant turn read back — and
asserts the three invariants that sequence broke:

  1. No invented time. A model may propose a thread, never a deadline.
  2. Sara's words are not evidence.
  3. One email conversation is one thread.
"""
from __future__ import annotations

import itertools
import uuid

import pytest

from sqlalchemy import BigInteger, create_engine, event as sa_event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import world_model
from app.models.world_model import WorldEvent, WorldThread
from app.services.world_state.catalog import get_spec
from app.services.world_state.reducer import reduce_world_event
from app.services.world_state.writer import append_world_event

USER = "test-user"
CONVERSATION_ID = "AAQkAGConversationLauraWeippert"

# The real thread. Note what is NOT in it: any time at all.
LAURA_EMAILS = [
    {
        "email_id": "email-1",
        "subject": "Connect with the Dave's",
        "sender_email": "laura@example.com",
        "sender_name": "Laura Weippert",
        "body_text": "Sending along an invite so we can connect. Looking forward to it.",
        "summary": "Laura sent a meeting invite.",
        "action_required": True,
    },
    {
        "email_id": "email-2",
        "subject": "RE: Connect with the Dave's",
        "sender_email": "laura@example.com",
        "sender_name": "Laura Weippert",
        "body_text": "Any chance we can move this call to tomorrow afternoon?",
        "summary": "Laura asks to reschedule.",
        "action_required": True,
    },
    {
        "email_id": "email-3",
        "subject": "RE: Connect with the Dave's",
        "sender_email": "laura@example.com",
        "sender_name": "Laura Weippert",
        "body_text": "Thank you!",
        "summary": "Laura acknowledges.",
        "action_required": False,
    },
]


# SQLite only autoincrements an INTEGER PRIMARY KEY; the world-model tables use
# BIGINT surrogate keys. Hand each one a value so the real append/reduce path can
# be exercised off Postgres.
_COUNTERS: dict = {}


@sa_event.listens_for(Session, "before_flush")
def _fill_bigint_keys(session, flush_context, instances):  # pragma: no cover
    for obj in session.new:
        for column in getattr(obj.__table__, "primary_key", []):
            if not isinstance(column.type, BigInteger):
                continue
            if getattr(obj, column.name, None) is None:
                counter = _COUNTERS.setdefault(
                    (obj.__tablename__, column.name), itertools.count(1),
                )
                setattr(obj, column.name, next(counter))


@pytest.fixture(autouse=True)
def world_events_enabled(monkeypatch):
    """The writer is a no-op when world events are disabled, and the suite
    disables them globally under pytest so no test writes real events. These
    tests are specifically about what the writer writes, so they re-enable it —
    via monkeypatch, scoped to each test, so the setting cannot leak into the
    rest of the run (it did, and it broke test_interoception_hygiene)."""
    monkeypatch.setenv("WORLD_EVENTS_ENABLED", "true")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    # Only the world-model tables: the shared metadata carries unrelated tables
    # whose foreign keys point outside it, and create_all would trip over them.
    world_model.Base.metadata.create_all(
        engine,
        tables=[
            t for name, t in world_model.Base.metadata.tables.items()
            if name.startswith("world_") or name == "sara_presence_snapshot"
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _emit(db, kind: str, payload: dict, **kwargs) -> WorldEvent:
    event = append_world_event(
        db, user_id=USER, kind=kind, source="test",
        dedupe_key=f"{kind}:{uuid.uuid4()}", payload=payload, **kwargs,
    )
    db.flush()
    reduce_world_event(db, event)
    db.flush()
    return event


def _threads(db) -> list:
    return list(db.execute(select(WorldThread)).scalars().all())


def _interpretation_of(source_kind: str, threads: list, payload_extra: dict | None = None) -> dict:
    """What the interpreter worker publishes after a model call."""
    return {
        "headline": "Updated my understanding",
        "detail": None,
        "entities": [],
        "facts": [],
        "threads": threads,
        "source_event_id": "src",
        "source_event_kind": source_kind,
        **(payload_extra or {}),
    }


class TestLauraReplay:
    def test_one_thread_per_conversation_with_no_due_date(self, db):
        for mail in LAURA_EMAILS:
            _emit(
                db, "email.analyzed",
                {**mail, "conversation_id": CONVERSATION_ID, "importance_score": 0.7},
                aggregate_type="email", aggregate_id=mail["email_id"],
                source_ref=f"email:{mail['email_id']}",
            )

        threads = [t for t in _threads(db) if t.kind == "follow_up"]
        assert len(threads) == 1, [t.thread_key for t in threads]
        assert threads[0].thread_key == f"email:{CONVERSATION_ID}"
        assert threads[0].due_at is None
        assert threads[0].due_provenance is None
        # Nothing open is open forever, even with no deadline.
        assert threads[0].next_review_at is not None

    def test_interpreter_due_date_is_discarded(self, db):
        """The exact failure: a thread proposed off 'tomorrow afternoon',
        carrying a 17:00Z deadline nothing in the email ever said."""
        _emit(
            db, "world.interpretation.completed",
            _interpretation_of("email.analyzed", [{
                "thread_key": f"email:{CONVERSATION_ID}",
                "kind": "commitment",
                "title": "Respond to Laura Weippert regarding call reschedule request",
                "next_step": "Reply with availability",
                "due_at": "2026-09-01T17:00:00+00:00",
                "priority": 0.7,
            }]),
            aggregate_type="email", aggregate_id="email-2",
        )

        threads = _threads(db)
        assert len(threads) == 1
        assert threads[0].due_at is None, "an invented deadline reached the thread"
        assert threads[0].due_provenance is None

    def test_explicit_datetime_in_source_text_is_accepted(self, db):
        """The inverse: when the sender actually writes a time, keep it —
        and record what vouched for it."""
        _emit(
            db, "email.analyzed",
            {
                "email_id": "email-4", "conversation_id": "conv-explicit",
                "subject": "Call", "action_required": True,
                "body_text": "Let's do Tue Sep 2 at 1:00 PM if that works.",
                "threads": [{
                    "thread_key": "email:conv-explicit",
                    "title": "Call with Laura",
                    "due_at": "2026-09-02T17:00:00+00:00",
                }],
            },
            aggregate_type="email", aggregate_id="email-4",
        )

        thread = next(t for t in _threads(db) if t.thread_key == "email:conv-explicit")
        assert thread.due_at is not None
        assert thread.due_provenance.startswith("source_text:")
        assert "Sep 2 at 1:00 PM" in thread.due_provenance

    def test_reminder_producer_keeps_its_real_time(self, db):
        _emit(
            db, "reminder.created",
            {"reminder_id": "rem-1", "title": "Call the vet",
             "due_at": "2026-09-05T14:00:00+00:00"},
            aggregate_type="reminder", aggregate_id="rem-1",
        )
        thread = next(t for t in _threads(db) if t.thread_key == "reminders:rem-1")
        assert thread.due_at is not None
        assert thread.due_provenance == "producer:reminder.created"


class TestSaraSpeechIsNotEvidence:
    def test_assistant_turn_is_never_interpreted(self):
        assert get_spec("chat.assistant_turn_stored").interpret is False
        assert get_spec("chat.user_turn_stored").interpret is True

    def test_threads_from_own_speech_are_discarded(self, db):
        """Even if an interpretation of Sara's own turn somehow reaches the
        reducer, it opens nothing."""
        before = len(_threads(db))
        _emit(
            db, "world.interpretation.completed",
            _interpretation_of("chat.assistant_turn_stored", [
                {"thread_key": "own-speech-1", "title": "Confirm availability for Laura's call"},
                {"thread_key": "own-speech-2", "title": "Provide extra BOP model file to Jim"},
            ]),
            aggregate_type="conversation", aggregate_id="conv-1",
        )
        assert len(_threads(db)) == before

    def test_assistant_turn_itself_opens_only_the_conversation_thread(self, db):
        _emit(
            db, "chat.assistant_turn_stored",
            {"conversation_id": "conv-2", "role": "assistant",
             "preview": "I'll draft a reply and confirm by 1 PM.",
             "threads": [{"thread_key": "invented", "title": "Confirm by 1 PM",
                          "due_at": "2026-09-01T17:00:00+00:00"}]},
            aggregate_type="conversation", aggregate_id="conv-2",
        )
        keys = {t.thread_key for t in _threads(db)}
        assert keys == {"conversation:conv-2"}


class TestDeliberationNoteRouting:
    @pytest.mark.parametrize("text,expected", [
        ("Draft reply to Laura Weippert about the reschedule", True),
        ("Organize notes about Jim Venezia", True),
        ("File the email from support@example.com", True),
        ("Consolidate duplicate tags in the knowledge garden", False),
        ("Archive notes older than a year", False),
    ])
    def test_person_and_email_proposals_are_flagged(self, text, expected):
        from app.services.deliberation_gate import _names_a_person_or_email

        class Proposal:
            description = text
            title = ""
            rationale = ""

        assert _names_a_person_or_email(Proposal()) is expected


class TestBriefPatchFilter:
    def test_signal_echo_is_rejected(self):
        from app.services.world_brief import _sanitize_patch_content

        assert _sanitize_patch_content(
            "happened", {"text": "New signal: email.analyzed from Laura"},
        ) is None
        assert _sanitize_patch_content(
            "happened", {"text": "Laura replied about the call (salience 0.62)"},
        ) is None

    def test_frozen_relative_time_is_stripped(self):
        from app.services.world_brief import _sanitize_patch_content

        cleaned = _sanitize_patch_content(
            "ahead", {"text": "Risk Ninja call — in 3h", "at": "2026-09-02T17:00:00Z"},
        )
        assert cleaned is not None
        assert "in 3h" not in cleaned["text"]
        assert cleaned["at"] == "2026-09-02T17:00:00Z"

    def test_happened_text_is_capped(self):
        from app.services.world_brief import _sanitize_patch_content

        cleaned = _sanitize_patch_content("happened", {"text": "word " * 400})
        assert len(cleaned["text"]) <= 302
