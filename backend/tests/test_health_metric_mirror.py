"""
HRV write-path tests (HRV_PIPELINE_AND_TWO_A_DAY_PROGRAM_2026_09_14 Part A).

The incident: on 2026-09-14 Sara said both "your HRV swung between 16 and 137
last week" and "no HRV logged in the last 36 hours" in one reply. Both were
faithful reads — of two stores that disagreed, because the iOS batch path only
emitted `hrv_morning` when the sync ran 05:00–07:59 local with a sample in the
preceding 4 hours, while `daily_recovery_log` took any sample in 24h.

`mirror_hrv_morning` makes the authoritative store (`health_metric`) receive
the reading at ingest. These tests pin the two things that make that safe: the
canonical 06:00 ET stamp (so a later real iOS row collides instead of
duplicating) and silence on junk input.
"""
import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.health_metric_mirror import canonical_recorded_at, mirror_hrv_morning

USER = "test-user-hrv"


@pytest.fixture
def db():
    """SQLite stand-in carrying the one constraint that matters: the dedup index."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    session = sessionmaker(bind=engine)()
    session.execute(text("""
        CREATE TABLE health_metric (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            metric_type TEXT NOT NULL,
            value NUMERIC NOT NULL,
            recorded_at TIMESTAMP NOT NULL,
            source TEXT NOT NULL,
            metadata TEXT
        )
    """))
    session.execute(text(
        "CREATE UNIQUE INDEX ix_health_metric_dedup "
        "ON health_metric (user_id, metric_type, recorded_at)"))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _rows(db):
    return db.execute(text(
        "SELECT value, recorded_at, source, metadata FROM health_metric "
        "WHERE metric_type='hrv_morning' ORDER BY recorded_at")).fetchall()


class TestCanonicalStamp:
    """The stamp must equal what iOS writes (`setHours(6,0,0,0)` local), or the
    dedup index stops deduping and every mirrored day doubles."""

    def test_september_is_0600_et_equals_1000_utc(self):
        ts = canonical_recorded_at(date(2026, 9, 14))
        assert ts.astimezone(timezone.utc) == datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

    def test_january_is_0600_et_equals_1100_utc(self):
        """EST, not EDT — a fixed -4 offset would land an hour off all winter."""
        ts = canonical_recorded_at(date(2026, 1, 14))
        assert ts.astimezone(timezone.utc) == datetime(2026, 1, 14, 11, 0, tzinfo=timezone.utc)

    def test_stamp_is_aware(self):
        assert canonical_recorded_at(date(2026, 9, 14)).tzinfo is not None


class TestBoundParameters:
    """Metadata and transaction ownership, checked at the call rather than in
    SQLite: pysqlite gives `CAST(… AS jsonb)` numeric affinity and does not emit
    real SAVEPOINTs, so neither survives a round-trip through the fake DB."""

    @staticmethod
    def _params(**kwargs):
        session = MagicMock()
        session.begin_nested.return_value.__enter__ = lambda s: s
        session.begin_nested.return_value.__exit__ = lambda s, *a: False
        mirror_hrv_morning(session, USER, 64, on_date=date(2026, 9, 14), **kwargs)
        return session, session.execute.call_args[0][1]

    def test_metadata_marks_a_single_morning_reading_and_its_origin(self):
        _, params = self._params(via="sync-recovery")
        meta = json.loads(params["meta"])
        assert meta == {"morning_reading": True, "sample_count": 1, "via": "sync-recovery"}

    def test_source_and_via_pass_through(self):
        session, params = self._params(source="manual", via="recovery-log")
        assert params["src"] == "manual"
        assert json.loads(params["meta"])["via"] == "recovery-log"

    def test_value_and_stamp_are_bound(self):
        _, params = self._params()
        assert params["mt"] == "hrv_morning"
        assert params["val"] == 64.0
        assert params["ts"].astimezone(timezone.utc) == datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

    def test_does_not_commit(self):
        """Callers own the transaction — the mirror must not commit a partial
        recovery-log write out from under them."""
        session, _ = self._params()
        session.commit.assert_not_called()


class TestMirrorWrites:
    def test_writes_the_reading(self, db):
        assert mirror_hrv_morning(db, USER, 64, on_date=date(2026, 9, 14)) is True
        rows = _rows(db)
        assert len(rows) == 1
        assert float(rows[0].value) == 64.0
        assert rows[0].source == "apple_health"

    def test_second_call_same_day_is_a_noop(self, db):
        assert mirror_hrv_morning(db, USER, 64, on_date=date(2026, 9, 14)) is True
        assert mirror_hrv_morning(db, USER, 64, on_date=date(2026, 9, 14)) is False
        assert len(_rows(db)) == 1

    def test_ios_hrv_morning_after_the_mirror_does_not_duplicate(self, db):
        """The real iOS row uses the identical stamp, so it collides — the day
        keeps one value rather than growing a second, disagreeing one."""
        mirror_hrv_morning(db, USER, 64, on_date=date(2026, 9, 14))
        ios_stamp = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)  # 06:00 ET
        inserted = db.execute(text("""
            INSERT INTO health_metric (id, user_id, metric_type, value, recorded_at, source, metadata)
            VALUES ('ios-1', :uid, 'hrv_morning', 71, :ts, 'apple_health', '{}')
            ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING
            RETURNING id
        """), {"uid": USER, "ts": ios_stamp}).fetchone()
        assert inserted is None
        assert len(_rows(db)) == 1

    def test_different_days_both_land(self, db):
        mirror_hrv_morning(db, USER, 137, on_date=date(2026, 9, 13))
        mirror_hrv_morning(db, USER, 64, on_date=date(2026, 9, 14))
        assert len(_rows(db)) == 2


class TestMirrorSkips:
    @pytest.mark.parametrize("bad", [None, 0, -5, float("nan"), float("inf"), "", "abc"])
    def test_junk_is_skipped_silently(self, db, bad):
        assert mirror_hrv_morning(db, USER, bad, on_date=date(2026, 9, 14)) is False
        assert _rows(db) == []

    def test_a_failing_write_does_not_poison_the_transaction(self, db):
        """A mirror failure must never cost the caller their real write."""
        db.execute(text("DROP TABLE health_metric"))
        assert mirror_hrv_morning(db, USER, 64, on_date=date(2026, 9, 14)) is False
        # the session is still usable
        assert db.execute(text("SELECT 1")).scalar() == 1
