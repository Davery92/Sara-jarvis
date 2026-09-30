"""PostgreSQL-backed coverage for the lesson tracker outcome-update SQL.

The original `UPDATE lesson_applications ... ORDER BY created_at DESC LIMIT 1`
is not valid PostgreSQL (UPDATE has no ORDER BY/LIMIT clause) and always
failed in production; SQLite silently accepts that syntax, so only a real
Postgres run catches this class of bug (chat harness repair Phase 6).

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_lesson_tracker_pg.py
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


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def _insert_lesson(pg) -> str:
    lid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO sara_reflection
            (id, reflection_type, domain, content, confidence, times_applied, effectiveness_score, is_active)
        VALUES
            (:id, 'mistake', 'general', 'test lesson', 0.8, 0, 0.5, true)
    """), {"id": lid})
    pg.commit()
    return lid


@pytest.fixture
def lesson_id(pg):
    lid = _insert_lesson(pg)
    yield lid
    # ON DELETE CASCADE on lesson_applications.lesson_id cleans up applications.
    pg.execute(text("DELETE FROM sara_reflection WHERE id = :l"), {"l": lid})
    pg.commit()


def _insert_application(pg, lesson_id, conversation_id, created_at_offset_seconds=0):
    app_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO lesson_applications (id, lesson_id, conversation_id, outcome, created_at)
        VALUES (:id, :lesson_id, :conversation_id, 'unknown', NOW() + (:offset || ' seconds')::interval)
    """), {
        "id": app_id,
        "lesson_id": lesson_id,
        "conversation_id": conversation_id,
        "offset": created_at_offset_seconds,
    })
    pg.commit()
    return app_id


@requires_pg
@pytest.mark.asyncio
async def test_record_success_updates_most_recent_unknown_application(pg, lesson_id):
    from app.services.lesson_tracker import lesson_tracker

    conversation_id = str(uuid.uuid4())
    older = _insert_application(pg, lesson_id, conversation_id, created_at_offset_seconds=-10)
    newer = _insert_application(pg, lesson_id, conversation_id, created_at_offset_seconds=0)

    await lesson_tracker.record_success(
        db=pg, lesson_id=lesson_id, conversation_id=conversation_id, feedback_signal="thanks"
    )

    rows = {
        str(r.id): r.outcome
        for r in pg.execute(text("SELECT id, outcome FROM lesson_applications WHERE lesson_id = :l"), {"l": lesson_id})
    }
    assert rows[newer] == "success"
    assert rows[older] == "unknown"


@requires_pg
@pytest.mark.asyncio
async def test_record_outcome_does_not_raise_on_no_pending_rows(pg, lesson_id):
    """No 'unknown' rows for this lesson/conversation: must not raise (this is
    the exact case where the old ORDER BY/LIMIT UPDATE blew up on Postgres)."""
    from app.services.lesson_tracker import lesson_tracker

    conversation_id = str(uuid.uuid4())
    await lesson_tracker.record_success(db=pg, lesson_id=lesson_id, conversation_id=conversation_id)
    # No exception means the CTE-based UPDATE parsed and ran.


@requires_pg
@pytest.mark.asyncio
async def test_record_outcome_is_idempotent(pg, lesson_id):
    from app.services.lesson_tracker import lesson_tracker

    conversation_id = str(uuid.uuid4())
    app_id = _insert_application(pg, lesson_id, conversation_id)

    await lesson_tracker.record_success(db=pg, lesson_id=lesson_id, conversation_id=conversation_id)
    score_after_first = pg.execute(
        text("SELECT effectiveness_score FROM sara_reflection WHERE id = :l"), {"l": lesson_id}
    ).scalar()

    # Re-running against the same (now non-'unknown') row must not error and
    # must not double-apply the EMA update.
    await lesson_tracker.record_success(db=pg, lesson_id=lesson_id, conversation_id=conversation_id)
    score_after_second = pg.execute(
        text("SELECT effectiveness_score FROM sara_reflection WHERE id = :l"), {"l": lesson_id}
    ).scalar()

    assert score_after_first == score_after_second

    outcome = pg.execute(
        text("SELECT outcome FROM lesson_applications WHERE id = :a"), {"a": app_id}
    ).scalar()
    assert outcome == "success"


@requires_pg
@pytest.mark.asyncio
async def test_update_pending_applications_bulk_updates_conversation(pg):
    from app.services.lesson_tracker import lesson_tracker

    conversation_id = str(uuid.uuid4())
    lesson_ids = [_insert_lesson(pg) for _ in range(3)]
    for lid in lesson_ids:
        _insert_application(pg, lid, conversation_id)

    try:
        updated = await lesson_tracker.update_pending_applications(
            db=pg, conversation_id=conversation_id, was_successful=True, feedback_signal="great"
        )

        assert set(updated) == set(lesson_ids)
        outcomes = pg.execute(
            text("SELECT outcome FROM lesson_applications WHERE conversation_id = :c"), {"c": conversation_id}
        ).scalars().all()
        assert all(o == "success" for o in outcomes)
    finally:
        for lid in lesson_ids:
            pg.execute(text("DELETE FROM sara_reflection WHERE id = :l"), {"l": lid})
        pg.commit()
