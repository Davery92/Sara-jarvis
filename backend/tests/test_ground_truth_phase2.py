"""Ground-truth Phase 2: everything open has a closer and an expiry.

Before this phase the only things that could close a `world_thread` were
`conversation.closed`, `workout.completed` and a task reaching a terminal state.
David answered Laura Weippert's email in twenty minutes and the thread nagged him
for two days, because nothing in the system read a sent reply as an answer and no
tool let him say so.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import BigInteger, create_engine, event as sa_event, select, text as sa_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import world_model
from app.models.world_model import WorldEvent, WorldThread
from app.services.world_state.catalog import get_spec
from app.services.world_state.reducer import reduce_world_event
from app.services.world_state.writer import append_world_event

USER = "test-user"
_COUNTERS: dict = {}


@sa_event.listens_for(Session, "before_flush")
def _fill_bigint_keys(session, flush_context, instances):  # pragma: no cover
    for obj in session.new:
        for column in getattr(obj.__table__, "primary_key", []):
            if isinstance(column.type, BigInteger) and getattr(obj, column.name, None) is None:
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
    world_model.Base.metadata.create_all(
        engine,
        tables=[
            t for name, t in world_model.Base.metadata.tables.items()
            if name.startswith("world_") or name == "sara_presence_snapshot"
        ],
    )
    # temporal.synthesize reads the calendar to emit started/ended events, and
    # the ORM selects every column — so the real table has to exist. SQLite can't
    # compile JSONB, so those columns become TEXT for the duration of the test.
    from sqlalchemy import Text
    from app.models.calendar_event import CalendarEvent
    for column in CalendarEvent.__table__.columns:
        if type(column.type).__name__ == "JSONB":
            column.type = Text()
    CalendarEvent.__table__.create(engine, checkfirst=True)
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


def _aware(dt: datetime) -> datetime:
    """SQLite strips tzinfo; Postgres does not. Normalize for assertions."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _open_email_thread(db, conversation_id: str = "conv-laura") -> WorldThread:
    _emit(
        db, "email.analyzed",
        {"email_id": "m1", "conversation_id": conversation_id,
         "subject": "Connect with the Dave's", "action_required": True,
         "summary": "Laura asks to reschedule."},
        aggregate_type="email", aggregate_id="m1",
    )
    return db.execute(select(WorldThread).where(
        WorldThread.thread_key == f"email:{conversation_id}"
    )).scalar_one()


class TestCloserEvents:
    def test_closer_kinds_are_registered(self):
        for kind in ("thread.resolved", "thread.expired"):
            assert get_spec(kind).domain == "time"
        # A resolution is not news.
        assert get_spec("thread.resolved").attention_base == 0.0

    def test_sent_reply_closes_the_conversation_thread(self, db):
        thread = _open_email_thread(db)
        assert thread.status == "open"

        _emit(
            db, "thread.resolved",
            {"thread_ids": [thread.id], "reason": "David replied to this conversation"},
            aggregate_type="world_thread", aggregate_id=thread.id,
        )
        db.refresh(thread)
        assert thread.status == "resolved"
        assert thread.resolved_at is not None

    def test_closing_by_thread_key_works(self, db):
        thread = _open_email_thread(db, "conv-key")
        _emit(
            db, "thread.resolved",
            {"thread_keys": ["email:conv-key"], "reason": "answered"},
            aggregate_type="world_thread", aggregate_id=thread.id,
        )
        db.refresh(thread)
        assert thread.status == "resolved"

    def test_a_closer_naming_nothing_closes_nothing(self, db):
        thread = _open_email_thread(db, "conv-safe")
        _emit(db, "thread.resolved", {"reason": "no target"},
              aggregate_type="world_thread", aggregate_id="not-a-thread")
        db.refresh(thread)
        assert thread.status == "open"


class TestExpiry:
    def test_undated_threads_get_a_review_date(self, db):
        thread = _open_email_thread(db, "conv-review")
        assert thread.due_at is None
        assert thread.next_review_at is not None
        # SQLite hands datetimes back naive, so compare on a common footing.
        review = _aware(thread.next_review_at)
        assert review > datetime.now(timezone.utc) + timedelta(days=2)

    def test_stale_threads_expire(self, db):
        from app.services.world_state.temporal import _expire_stale_threads

        thread = _open_email_thread(db, "conv-stale")
        thread.updated_at = datetime.now(timezone.utc) - timedelta(days=20)
        db.flush()

        assert _expire_stale_threads(db, datetime.now(timezone.utc)) == 1
        db.flush()
        db.refresh(thread)
        assert thread.status == "expired"

    def test_overdue_threads_expire_after_the_grace_period(self, db):
        from app.services.world_state.temporal import _expire_stale_threads

        thread = _open_email_thread(db, "conv-overdue")
        thread.due_at = datetime.now(timezone.utc) - timedelta(hours=72)
        db.flush()

        assert _expire_stale_threads(db, datetime.now(timezone.utc)) == 1
        db.flush()
        db.refresh(thread)
        assert thread.status == "expired"


class TestOverdueFiresOnce:
    def test_overdue_moves_the_thread_out_of_the_active_set(self, db):
        """The thread stays visible but stops being fresh news every sweep."""
        from app.services.world_state import temporal

        thread = _open_email_thread(db, "conv-once")
        thread.due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.flush()

        temporal.synthesize(db)
        db.refresh(thread)
        assert thread.status == "overdue"

        # A second sweep must not re-announce it.
        before = db.execute(select(WorldEvent).where(
            WorldEvent.kind == "thread.overdue"
        )).scalars().all()
        temporal.synthesize(db)
        after = db.execute(select(WorldEvent).where(
            WorldEvent.kind == "thread.overdue"
        )).scalars().all()
        assert len(after) == len(before) == 1

    def test_the_overdue_payload_carries_rendered_time_not_a_stamp(self, db):
        from app.services.world_state import temporal

        thread = _open_email_thread(db, "conv-text")
        thread.due_at = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)
        db.flush()
        temporal.synthesize(db)

        event = db.execute(select(WorldEvent).where(
            WorldEvent.kind == "thread.overdue"
        )).scalars().one()
        # 17:00Z is 1:00 PM ET — the exact number Sara rendered as "5:00 AM EDT".
        assert "1:00 PM ET" in event.payload["due_text"]


class TestResolutionQueryTerms:
    def test_filler_words_never_match_a_thread(self):
        from app.services.thread_resolution import query_terms

        assert query_terms("we had the meeting") == []
        assert query_terms("stop talking about it") == []

    def test_a_name_survives(self):
        from app.services.thread_resolution import query_terms

        assert query_terms(
            "ENOUGH WITH THE LAURA WEIPPERT OVERDUE NONSENSE WE HAD OUR MEETING"
        ) == ["laura", "weippert", "overdue", "nonsense"]


class TestResolutionIsNotOverEager:
    """Closing the wrong thread silently drops real work.

    Found live on 2026-09-02: `resolve_entity(query="Laura Weippert")` matched
    "Check if John Willenborg has contacted" and an unrelated risk-research
    thread — both of which mention DEREK Weippert — and closed them. Matching on
    any one word of a name is not matching a name.
    """

    def test_a_shared_surname_alone_is_not_a_match(self):
        from app.services.thread_resolution import _required_matches, query_terms

        terms = query_terms("Laura Weippert")
        assert terms == ["laura", "weippert"]
        # A Derek Weippert thread contains one of these; a Laura thread, both.
        assert _required_matches(terms) == 2

    def test_a_full_sentence_still_matches_on_two_words(self):
        """The intercept passes David's whole message, so requiring EVERY word
        would match nothing — "nonsense" appears in no thread title."""
        from app.services.thread_resolution import _required_matches, query_terms

        terms = query_terms(
            "ENOUGH WITH THE LAURA WEIPPERT OVERDUE NONSENSE WE HAD OUR MEETING"
        )
        assert _required_matches(terms) == 2
        assert "laura" in terms and "weippert" in terms

    def test_a_single_word_query_needs_only_its_one_word(self):
        from app.services.thread_resolution import _required_matches, query_terms

        assert _required_matches(query_terms("Salem")) == 1


class TestChatIntercept:
    @pytest.mark.parametrize("message", [
        "we had our meeting with Laura Weippert",
        "I already handled that",
        "enough about the Laura Weippert thing",
        "stop bugging me about the AWS invoice",
        "it's done",
    ])
    def test_resolution_phrases_are_recognised(self, message):
        from app.services.chat_intercepts import _RESOLUTION_PATTERNS
        assert _RESOLUTION_PATTERNS.search(message) is not None

    @pytest.mark.parametrize("message", [
        "what's on my calendar today?",
        "can you draft a reply to Laura?",
        "how did the deploy go",
    ])
    def test_ordinary_messages_are_not_intercepted(self, message):
        from app.services.chat_intercepts import _RESOLUTION_PATTERNS
        assert _RESOLUTION_PATTERNS.search(message) is None


class TestCloserCoverage:
    def test_every_registered_thread_kind_names_its_closer(self):
        from app.tasks.system_wiring_check import THREAD_KIND_CLOSERS

        assert THREAD_KIND_CLOSERS
        for kind, closer in THREAD_KIND_CLOSERS.items():
            assert closer, f"{kind} has no closer"
