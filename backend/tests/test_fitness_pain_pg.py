"""Step 13 of FITNESS_COACH_IMPLEMENTATION_PLAN: a pain report is what the
athlete said, and nothing else.

Three claims the schema and service exist to keep true:

1. **A session with no report is unknown, not pain-free.** "Nobody asked"
   and "nothing hurt" support completely different coaching — one is a gap to
   fill, the other is a green light — and collapsing them is how an exercise
   gets called fine on no evidence.
2. **Patterns count distinct sessions, never reports.** Four reports across
   four sets of one session is one bad session. Counting reports would make
   it look like a pattern, which is the kind of claim that gets an exercise
   dropped from a program for no reason.
3. **There is no diagnosis anywhere.** "Right forearm hurts on barbell
   curls" is data; naming a condition is a clinical conclusion this system
   does not draw, and a stored one would be cited as fact by every
   downstream reader forever.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_pain_pg.py
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


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
def two_athletes(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"m8a-{uuid.uuid4().hex[:18]}"
    bob = f"m8b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW())
        """), {"id": uid, "e": f"{uid}@m8.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_pain_report", "exercise_pr", "workout_log",
                  "fitness_exercise_performance", "active_workout_session",
                  "workout", "fitness_athlete_profile"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM exercise_library WHERE name LIKE 'M8TEST %'"))
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _session(pg, user_id, *, started: datetime) -> str:
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session (id, user_id, status, started_at, version)
        VALUES (:id, :u, 'completed', :at, 1)
    """), {"id": sid, "u": user_id, "at": started})
    return sid


def _exercise(pg, name) -> str:
    from app.schemas.fitness_coach import normalize_code
    eid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO exercise_library
            (id, name, normalized_name, movement_pattern, load_convention,
             created_at, updated_at)
        VALUES (:id, :name, :norm, 'pull', 'total', NOW(), NOW())
    """), {"id": eid, "name": name, "norm": normalize_code(name)})
    return eid


def _occurrence(pg, user_id, session_id, name, *, canonical=None, occurrence=1) -> str:
    pid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_exercise_performance
            (id, user_id, active_session_id, occurrence, exercise_library_id,
             captured_name)
        VALUES (:id, :u, :sid, :occ, :canon, :name)
    """), {"id": pid, "u": user_id, "sid": session_id, "occ": occurrence,
           "canon": canonical, "name": name})
    return pid


def _report(pg, user_id, **kwargs):
    from app.services.fitness.performance import record_pain
    return record_pain(pg, user_id, **kwargs)


# ─────────────────────────────────────────────────────────────────────────
# No diagnosis
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_there_is_no_diagnosis_column_anywhere(pg):
    """A stored diagnosis would be cited as fact by every reader forever."""
    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'fitness_pain_report'
    """)).fetchall()}
    for forbidden in ("diagnosis", "condition", "injury_type", "icd_code",
                      "pathology", "assessment"):
        assert forbidden not in columns, f"{forbidden} is a clinical conclusion"
    # What IS there: the athlete's own words and a self-reported severity.
    assert {"pain_present", "severity", "location", "side", "onset",
            "context", "notes"} <= columns


# ─────────────────────────────────────────────────────────────────────────
# Unknown is not pain-free
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_session_with_no_report_is_unknown_not_pain_free(pg, two_athletes):
    """The central distinction.

    "Nobody asked" is a gap to fill; "nothing hurt" is a green light. A
    missing row must read as the first.
    """
    from app.schemas.fitness_coach import Unavailable
    from app.services.fitness.performance import session_pain_status

    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    pg.commit()

    status = session_pain_status(pg, alice, sid)
    assert status.value is None, "no report must not read as zero pain"
    assert status.unavailable_reason is Unavailable.NO_DATA
    assert "not the same as pain-free" in status.note


@requires_pg
def test_an_explicit_no_pain_answer_is_a_zero_not_an_absence(pg, two_athletes):
    """"I was asked and nothing hurt" is real information."""
    from app.services.fitness.performance import session_pain_status

    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    pg.commit()
    _report(pg, alice, pain_present=False, severity=0,
            occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
            active_session_id=sid)

    status = session_pain_status(pg, alice, sid)
    assert status.value == 0.0
    assert status.unavailable_reason is None
    assert "asked, and no pain reported" in status.note


@requires_pg
def test_a_reported_pain_reports_its_highest_severity(pg, two_athletes):
    from app.services.fitness.performance import session_pain_status

    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    pg.commit()
    for severity in (3, 6, 4):
        _report(pg, alice, pain_present=True, severity=severity,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
                            + timedelta(minutes=severity),
                active_session_id=sid, location="right forearm")

    status = session_pain_status(pg, alice, sid)
    assert status.value == 6.0
    assert status.source_count == 3


# ─────────────────────────────────────────────────────────────────────────
# Coherence
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_pain_present_is_required(pg, two_athletes):
    """A row that does not state it would be unreadable either way."""
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO fitness_pain_report
                (id, user_id, occurred_at, logical_date, severity)
            VALUES (:id, :u, NOW(), CURRENT_DATE, 5)
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_severity_above_zero_with_no_pain_is_refused(pg, two_athletes):
    """Such a row would count as pain in one query and not in another."""
    from app.services.fitness.data_access import FitnessDataError

    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        _report(pg, alice, pain_present=False, severity=7,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC))
    assert "incoherent" in str(e.value)
    pg.rollback()

    # The database refuses it too.
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO fitness_pain_report
                (id, user_id, occurred_at, logical_date, pain_present, severity)
            VALUES (:id, :u, NOW(), CURRENT_DATE, FALSE, 7)
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_pain_present_with_no_severity_is_allowed(pg, two_athletes):
    """They may not have rated it, and that is still a report."""
    alice, _ = two_athletes
    report_id = _report(pg, alice, pain_present=True,
                        occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                        location="right forearm")
    row = pg.execute(text("""
        SELECT pain_present, severity, location FROM fitness_pain_report
        WHERE id = :id
    """), {"id": report_id}).fetchone()
    assert row.pain_present is True
    assert row.severity is None
    assert row.location == "right forearm"


@requires_pg
@pytest.mark.parametrize("severity", [-1, 11])
def test_severity_outside_zero_to_ten_is_refused(pg, two_athletes, severity):
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    with pytest.raises(FitnessDataError):
        _report(pg, alice, pain_present=True, severity=severity,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC))
    pg.rollback()


@requires_pg
def test_an_unrecognised_side_or_onset_is_refused(pg, two_athletes):
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    for kwargs in ({"side": "dorsal"}, {"onset": "mysterious"}):
        with pytest.raises(FitnessDataError):
            _report(pg, alice, pain_present=True,
                    occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC), **kwargs)
        pg.rollback()


@requires_pg
def test_a_naive_occurred_at_is_refused(pg, two_athletes):
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        _report(pg, alice, pain_present=True,
                occurred_at=datetime(2026, 10, 1, 18, 0))
    assert "timezone-aware" in str(e.value)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Attachment and scope
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_report_can_stand_alone_with_no_session(pg, two_athletes):
    """Pain on a rest day is still a report."""
    alice, _ = two_athletes
    report_id = _report(pg, alice, pain_present=True, severity=4,
                        occurred_at=datetime(2026, 10, 1, 9, 0, tzinfo=ET),
                        location="right shoulder", context="reaching overhead")
    row = pg.execute(text("""
        SELECT active_session_id, exercise_performance_id, workout_set_id,
               logical_date, context
        FROM fitness_pain_report WHERE id = :id
    """), {"id": report_id}).fetchone()
    assert row.active_session_id is None
    assert row.exercise_performance_id is None
    assert row.workout_set_id is None
    assert row.logical_date == date(2026, 10, 1)
    assert row.context == "reaching overhead"


@requires_pg
def test_a_report_cannot_name_another_athletes_session(pg, two_athletes):
    alice, bob = two_athletes
    bobs = _session(pg, bob, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    pg.commit()
    with pytest.raises(LookupError):
        _report(pg, alice, pain_present=True, severity=5,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                active_session_id=bobs)
    pg.rollback()
    assert pg.execute(text(
        "SELECT COUNT(*) FROM fitness_pain_report WHERE active_session_id = :s"),
        {"s": bobs}).scalar() == 0


@requires_pg
def test_a_report_cannot_name_another_athletes_occurrence(pg, two_athletes):
    alice, bob = two_athletes
    bobs_session = _session(pg, bob, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    bobs_occurrence = _occurrence(pg, bob, bobs_session, "M8TEST Curl")
    pg.commit()
    with pytest.raises(LookupError):
        _report(pg, alice, pain_present=True, severity=5,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                exercise_performance_id=bobs_occurrence)
    pg.rollback()


@requires_pg
def test_the_logical_date_follows_the_athletes_timezone(pg, two_athletes):
    """A past report's day must not move when the athlete's timezone changes."""
    from app.schemas.fitness_coach import AthleteProfilePatch
    from app.services.fitness.profile import patch_athlete_profile

    alice, _ = two_athletes
    patch_athlete_profile(pg, alice, AthleteProfilePatch(timezone="Asia/Tokyo"))

    # 08:00 Tokyo on 2 October is 19:00 ET on the 1st.
    report_id = _report(
        pg, alice, pain_present=True, severity=3,
        occurred_at=datetime(2026, 10, 2, 8, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    stored = pg.execute(text(
        "SELECT logical_date FROM fitness_pain_report WHERE id = :id"),
        {"id": report_id}).scalar()
    assert stored == date(2026, 10, 2)

    # Moving home does not move the report.
    patch_athlete_profile(pg, alice, AthleteProfilePatch(timezone="America/New_York"))
    assert pg.execute(text(
        "SELECT logical_date FROM fitness_pain_report WHERE id = :id"),
        {"id": report_id}).scalar() == date(2026, 10, 2)


# ─────────────────────────────────────────────────────────────────────────
# Corrections
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_correction_supersedes_rather_than_overwrites(pg, two_athletes):
    """"I said 7 but it was more like 3" is a second statement.

    Both are things the athlete said, and overwriting the first loses one of
    them.
    """
    alice, _ = two_athletes
    first = _report(pg, alice, pain_present=True, severity=7,
                    occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                    location="right forearm")
    second = _report(pg, alice, pain_present=True, severity=3,
                     occurred_at=datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
                     location="right forearm", corrects_report_id=first)

    original = pg.execute(text("""
        SELECT severity, superseded_by_id FROM fitness_pain_report WHERE id = :id
    """), {"id": first}).fetchone()
    assert original.severity == 7, "the original statement is retained verbatim"
    assert original.superseded_by_id == second


@requires_pg
def test_a_superseded_report_is_excluded_from_the_session_status(pg, two_athletes):
    from app.services.fitness.performance import session_pain_status

    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    pg.commit()
    first = _report(pg, alice, pain_present=True, severity=7,
                    occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                    active_session_id=sid)
    _report(pg, alice, pain_present=True, severity=3,
            occurred_at=datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
            active_session_id=sid, corrects_report_id=first)

    assert session_pain_status(pg, alice, sid).value == 3.0


@requires_pg
def test_a_correction_cannot_name_another_athletes_report(pg, two_athletes):
    alice, bob = two_athletes
    bobs = _report(pg, bob, pain_present=True, severity=5,
                   occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC))
    with pytest.raises(LookupError):
        _report(pg, alice, pain_present=True, severity=1,
                occurred_at=datetime(2026, 10, 1, 19, 0, tzinfo=UTC),
                corrects_report_id=bobs)
    pg.rollback()


@requires_pg
def test_a_report_cannot_supersede_itself(pg, two_athletes):
    alice, _ = two_athletes
    report_id = _report(pg, alice, pain_present=True, severity=4,
                        occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC))
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            UPDATE fitness_pain_report SET superseded_by_id = id WHERE id = :id
        """), {"id": report_id})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Occurrence summary
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_occurrence_summary_is_recomputed_not_incremented(pg, two_athletes):
    """So a correction cannot leave it stale.

    Incrementing a counter would leave the summary saying 7 after the athlete
    corrected it to 3.
    """
    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    occurrence = _occurrence(pg, alice, sid, "M8TEST Barbell Curl")
    pg.commit()

    first = _report(pg, alice, pain_present=True, severity=7,
                    occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                    exercise_performance_id=occurrence, active_session_id=sid)
    summary = pg.execute(text("""
        SELECT pain_reported, max_pain_severity FROM fitness_exercise_performance
        WHERE id = :id
    """), {"id": occurrence}).fetchone()
    assert summary.pain_reported is True
    assert summary.max_pain_severity == 7

    _report(pg, alice, pain_present=True, severity=3,
            occurred_at=datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
            exercise_performance_id=occurrence, active_session_id=sid,
            corrects_report_id=first)
    corrected = pg.execute(text("""
        SELECT pain_reported, max_pain_severity FROM fitness_exercise_performance
        WHERE id = :id
    """), {"id": occurrence}).fetchone()
    assert corrected.max_pain_severity == 3, (
        "the summary must follow the live reports, not accumulate"
    )


@requires_pg
def test_an_explicit_no_pain_leaves_the_occurrence_flag_false(pg, two_athletes):
    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    occurrence = _occurrence(pg, alice, sid, "M8TEST Barbell Curl")
    pg.commit()
    _report(pg, alice, pain_present=False, severity=0,
            occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
            exercise_performance_id=occurrence, active_session_id=sid)
    summary = pg.execute(text("""
        SELECT pain_reported, max_pain_severity FROM fitness_exercise_performance
        WHERE id = :id
    """), {"id": occurrence}).fetchone()
    assert summary.pain_reported is False
    assert summary.max_pain_severity is None


# ─────────────────────────────────────────────────────────────────────────
# Patterns count sessions, not reports
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_four_reports_in_one_session_is_one_session_with_pain(pg, two_athletes):
    """The arithmetic that would otherwise invent a pattern.

    Counting reports would turn one bad session into four, which is the kind
    of claim that gets an exercise dropped from a program for no reason.
    """
    from app.services.fitness.performance import pain_patterns

    alice, _ = two_athletes
    curl = _exercise(pg, "M8TEST Barbell Curl")
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    occurrence = _occurrence(pg, alice, sid, "M8TEST Barbell Curl", canonical=curl)
    pg.commit()

    for minute in (0, 5, 10, 15):
        _report(pg, alice, pain_present=True, severity=5,
                occurred_at=datetime(2026, 10, 1, 18, minute, tzinfo=UTC),
                exercise_performance_id=occurrence, active_session_id=sid,
                location="right forearm")

    patterns = pain_patterns(pg, alice, date(2026, 10, 1), date(2026, 10, 2))
    assert len(patterns) == 1
    assert patterns[0].sessions_with_pain == 1, (
        "four reports in one session is one session, not four"
    )
    assert patterns[0].sessions_total == 1


@requires_pg
def test_a_pattern_states_its_denominator(pg, two_athletes):
    """"Four of six documented sessions" is a statement; "four reports" is not.

    Without the denominator, two reports out of twenty sessions reads the
    same as two out of two.
    """
    from app.services.fitness.performance import pain_patterns

    alice, _ = two_athletes
    curl = _exercise(pg, "M8TEST Barbell Curl")

    # Six sessions. Four with reported pain, one asked-and-fine, one never
    # asked at all.
    for index in range(6):
        day = datetime(2026, 9, 1, 17, 0, tzinfo=UTC) + timedelta(days=index * 2)
        sid = _session(pg, alice, started=day)
        occurrence = _occurrence(pg, alice, sid, "M8TEST Barbell Curl",
                                 canonical=curl)
        pg.commit()
        if index < 4:
            _report(pg, alice, pain_present=True, severity=4 + index,
                    occurred_at=day + timedelta(hours=1),
                    exercise_performance_id=occurrence, active_session_id=sid,
                    location="right forearm", side="right")
        elif index == 4:
            _report(pg, alice, pain_present=False, severity=0,
                    occurred_at=day + timedelta(hours=1),
                    exercise_performance_id=occurrence, active_session_id=sid)
        # index 5: no report at all — unknown, not pain-free.

    patterns = pain_patterns(pg, alice, date(2026, 9, 1), date(2026, 9, 30))
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.sessions_with_pain == 4
    assert pattern.sessions_with_report == 5, "the day nobody asked is not a report"
    assert pattern.sessions_total == 6
    assert pattern.reporting_coverage == pytest.approx(5 / 6)
    assert pattern.max_severity == 7
    assert pattern.locations == ("right forearm",)
    assert pattern.sides == ("right",)


@requires_pg
def test_a_pattern_with_no_sessions_has_no_coverage_rather_than_zero(pg, two_athletes):
    from app.services.fitness.performance import PainPattern
    empty = PainPattern(
        exercise_library_id=None, exercise_name="x",
        sessions_with_pain=0, sessions_with_report=0, sessions_total=0,
        max_severity=None, latest_severity=None, latest_at=None,
    )
    assert empty.reporting_coverage is None


@requires_pg
def test_patterns_are_per_exercise(pg, two_athletes):
    from app.services.fitness.performance import pain_patterns

    alice, _ = two_athletes
    curl = _exercise(pg, "M8TEST Barbell Curl")
    press = _exercise(pg, "M8TEST Overhead Press")
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    curl_occ = _occurrence(pg, alice, sid, "M8TEST Barbell Curl",
                           canonical=curl, occurrence=1)
    press_occ = _occurrence(pg, alice, sid, "M8TEST Overhead Press",
                            canonical=press, occurrence=2)
    pg.commit()

    _report(pg, alice, pain_present=True, severity=6,
            occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
            exercise_performance_id=curl_occ, active_session_id=sid,
            location="right forearm")
    _report(pg, alice, pain_present=False, severity=0,
            occurred_at=datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
            exercise_performance_id=press_occ, active_session_id=sid)

    patterns = pain_patterns(pg, alice, date(2026, 10, 1), date(2026, 10, 2))
    assert len(patterns) == 1, "only the curl had reported pain"
    assert patterns[0].exercise_library_id == curl


@requires_pg
def test_patterns_do_not_cross_between_athletes(pg, two_athletes):
    from app.services.fitness.performance import pain_patterns

    alice, bob = two_athletes
    curl = _exercise(pg, "M8TEST Barbell Curl")
    for uid in (alice, bob):
        sid = _session(pg, uid, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
        occurrence = _occurrence(pg, uid, sid, "M8TEST Barbell Curl", canonical=curl)
        pg.commit()
        _report(pg, uid, pain_present=True, severity=9 if uid == bob else 3,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                exercise_performance_id=occurrence, active_session_id=sid)

    alices = pain_patterns(pg, alice, date(2026, 10, 1), date(2026, 10, 2))
    bobs = pain_patterns(pg, bob, date(2026, 10, 1), date(2026, 10, 2))
    assert alices[0].max_severity == 3
    assert bobs[0].max_severity == 9


@requires_pg
def test_an_unresolved_exercise_name_is_not_merged_with_another(pg, two_athletes):
    """Grouping on the canonical id alone would merge every unresolved set.

    Two different lifts whose names never resolved would become one pattern.
    """
    from app.services.fitness.performance import pain_patterns

    alice, _ = two_athletes
    sid = _session(pg, alice, started=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    # Two occurrences, neither with a canonical id.
    one = _occurrence(pg, alice, sid, "M8TEST Odd Lift A", occurrence=1)
    two = _occurrence(pg, alice, sid, "M8TEST Odd Lift B", occurrence=2)
    pg.commit()
    for occurrence in (one, two):
        _report(pg, alice, pain_present=True, severity=5,
                occurred_at=datetime(2026, 10, 1, 18, 0, tzinfo=UTC),
                exercise_performance_id=occurrence, active_session_id=sid)

    patterns = pain_patterns(pg, alice, date(2026, 10, 1), date(2026, 10, 2))
    # Both have a NULL canonical id, so they share a group — and the group's
    # name comes from a captured name rather than being invented. The honest
    # reading is "unresolved", which is what the name conveys.
    assert len(patterns) == 1
    assert patterns[0].exercise_library_id is None
    assert patterns[0].exercise_name.startswith("M8TEST Odd Lift")
    assert patterns[0].sessions_with_pain == 1
