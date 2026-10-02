"""Step 24 of FITNESS_COACH_IMPLEMENTATION_PLAN: coaching cadences are
per-athlete, opt-in, and cannot produce two reviews for one occurrence.

The three completion criteria, each a section below:

* **All cadences configurable, per-user and opt-in.** Every preference
  starts disabled AND unconsented, and those are different questions: one is
  "is this on", the other is "may we contact you about it".
* **Retry/restart never produces two reviews per occurrence.** The unique
  index on `(user_id, kind, occurrence_at)` is what makes that true.
  `DBScheduler` seeds UTC `last_run_at`, so a daily ET cron DOES fire twice
  (see `test_db_scheduler_beat_double_fire.py`) — the ledger absorbs it.
* **Global schedule configuration cannot be hijacked through athlete
  settings.** The sweep is one global row; the athlete's API has no
  parameter for a task name, a queue or an owner.

Plus the arithmetic nobody gets right by accident: a 14-day cadence that
actually means fourteen days, and DST's repeated and skipped hours.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_coaching_schedules_pg.py
"""
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

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
    alice = f"s24a-{uuid.uuid4().hex[:17]}"
    bob = f"s24b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s24.invalid", "p": unusable_hash})
        pg.execute(text("""
            INSERT INTO fitness_athlete_profile
                (id, user_id, timezone, created_at, updated_at)
            VALUES (:i, :u, 'America/New_York', NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
        """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_coaching_job_run", "fitness_coaching_schedule",
                  "fitness_coach_recommendation", "fitness_coach_review",
                  "fitness_athlete_profile", "health_metric", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _enable(pg, user_id, kind="daily_checkin", **kwargs):
    from app.services.fitness.coaching_jobs import set_schedule
    schedule = set_schedule(
        pg, user_id, kind, enabled=True, consented=True, **kwargs,
    )
    pg.commit()
    return schedule


# ─────────────────────────────────────────────────────────────────────────
# Opt-in, per kind
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_every_cadence_starts_off_and_unconsented(pg, two_athletes):
    """Two switches, because they are different questions. A cadence that
    computes and stores without delivering is a legitimate state; delivering
    without consent is not."""
    from app.services.fitness.coaching_jobs import CADENCE_KINDS, list_schedules

    alice, _ = two_athletes
    schedules = list_schedules(pg, alice)
    assert {s.kind for s in schedules} == set(CADENCE_KINDS)
    for schedule in schedules:
        assert schedule.enabled is False, schedule.kind
        assert schedule.consented is False, schedule.kind
        assert schedule.active is False, schedule.kind


@requires_pg
def test_reading_the_cadences_creates_nothing(pg, two_athletes):
    """A read that wrote would mean opening a settings screen enrolled the
    athlete in six cadences."""
    from app.services.fitness.coaching_jobs import list_schedules

    alice, _ = two_athletes
    list_schedules(pg, alice)
    list_schedules(pg, alice)
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coaching_schedule WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_enabling_one_kind_does_not_enable_the_others(pg, two_athletes):
    """"Turn on coaching" as one switch would make a weigh-in nudge and a
    minute of GPU time the same decision."""
    from app.services.fitness.coaching_jobs import list_schedules

    alice, _ = two_athletes
    _enable(pg, alice, "daily_checkin")

    by_kind = {s.kind: s for s in list_schedules(pg, alice)}
    assert by_kind["daily_checkin"].active is True
    assert by_kind["weekly_review"].active is False
    assert by_kind["progress_photo"].active is False


@requires_pg
def test_consent_carries_a_timestamp(pg, two_athletes):
    """"Consented at some point" is not a record of consent."""
    alice, _ = two_athletes
    schedule = _enable(pg, alice, "weekly_review")
    assert schedule.consented_at is not None


@requires_pg
def test_withdrawing_consent_clears_the_timestamp(pg, two_athletes):
    """Otherwise a later row looks retroactively consented."""
    from app.services.fitness.coaching_jobs import set_schedule

    alice, _ = two_athletes
    _enable(pg, alice, "weekly_review")
    updated = set_schedule(pg, alice, "weekly_review", consented=False)
    pg.commit()
    assert updated.consented is False
    assert updated.consented_at is None
    assert updated.active is False


@requires_pg
def test_two_athletes_keep_separate_cadences(pg, two_athletes):
    from app.services.fitness.coaching_jobs import get_schedule

    alice, bob = two_athletes
    _enable(pg, alice, "daily_checkin", local_time=time(6, 30))
    _enable(pg, bob, "daily_checkin", local_time=time(9, 0),
            timezone_name="Europe/London")

    a = get_schedule(pg, alice, "daily_checkin")
    b = get_schedule(pg, bob, "daily_checkin")
    assert a.local_time == time(6, 30) and a.timezone == "America/New_York"
    assert b.local_time == time(9, 0) and b.timezone == "Europe/London"
    assert a.next_due_at != b.next_due_at


@requires_pg
def test_an_unknown_kind_is_refused(pg, two_athletes):
    from app.services.fitness.coaching_jobs import set_schedule
    from app.services.fitness.data_access import FitnessDataError

    alice, _ = two_athletes
    with pytest.raises(FitnessDataError):
        set_schedule(pg, alice, "nag_me_constantly", enabled=True)


@requires_pg
def test_a_bad_timezone_is_refused_at_write_time(pg, two_athletes):
    """Strictly on the write path.

    `athlete_zone` falls back to ET with a warning, which is right for a
    read — an existing bad row must not break the state — and wrong here:
    accepting an unknown zone stores something that silently becomes ET
    forever, and the athlete sees their 07:00 fire at the wrong time with no
    explanation.
    """
    from app.services.fitness.coaching_jobs import set_schedule
    from app.services.fitness.data_access import FitnessDataError

    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as excinfo:
        set_schedule(pg, alice, "daily_checkin", enabled=True,
                     timezone_name="Mars/Olympus_Mons")
    assert "not a known timezone" in str(excinfo.value)
    pg.rollback()
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coaching_schedule WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_a_real_timezone_is_accepted(pg, two_athletes):
    from app.services.fitness.coaching_jobs import set_schedule

    alice, _ = two_athletes
    schedule = set_schedule(
        pg, alice, "daily_checkin", enabled=True, consented=True,
        timezone_name="Pacific/Auckland",
    )
    pg.commit()
    assert schedule.timezone == "Pacific/Auckland"
    assert schedule.next_due_at is not None


@requires_pg
def test_a_stale_version_is_a_conflict(pg, two_athletes):
    from app.services.fitness.coaching_jobs import CadenceConflict, set_schedule

    alice, _ = two_athletes
    first = _enable(pg, alice, "daily_checkin")
    with pytest.raises(CadenceConflict) as excinfo:
        set_schedule(pg, alice, "daily_checkin", enabled=False,
                     expected_version=first.version - 1)
    assert excinfo.value.current_version == first.version


# ─────────────────────────────────────────────────────────────────────────
# Due-time arithmetic
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_fourteen_day_cadence_means_fourteen_days(pg, two_athletes):
    """A cron's `*/14` on the day-of-month field means the 1st, 15th and
    29th — so January gives 14 days, 14 days, then 3. An anchor plus a count
    is the only arithmetic that means what it says."""
    from app.services.fitness.coaching_jobs import compute_next_due

    alice, _ = two_athletes
    schedule = _enable(
        pg, alice, "biweekly_review",
        cadence_days=14, anchor_date=date(2026, 1, 1), local_time=time(7, 0),
    )

    seen = []
    moment = datetime(2026, 1, 1, 0, 0, tzinfo=ET)
    for _ in range(5):
        due = compute_next_due(schedule, after=moment)
        assert due is not None
        seen.append(due.astimezone(ET).date())
        moment = due + timedelta(minutes=1)

    gaps = [(b - a).days for a, b in zip(seen, seen[1:])]
    assert gaps == [14, 14, 14, 14], (seen, gaps)
    # And the dates are NOT the cron ones.
    assert seen[:3] == [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29)]
    assert seen[3] == date(2026, 2, 12), "a cron would have said February 1"


@requires_pg
def test_a_twenty_eight_day_cadence_does_not_drift_with_month_length(
    pg, two_athletes,
):
    from app.services.fitness.coaching_jobs import compute_next_due

    alice, _ = two_athletes
    schedule = _enable(
        pg, alice, "progress_photo",
        cadence_days=28, anchor_date=date(2026, 1, 3), local_time=time(8, 0),
    )
    moment = datetime(2026, 1, 3, 0, 0, tzinfo=ET)
    seen = []
    for _ in range(4):
        due = compute_next_due(schedule, after=moment)
        seen.append(due.astimezone(ET).date())
        moment = due + timedelta(minutes=1)
    assert [(b - a).days for a, b in zip(seen, seen[1:])] == [28, 28, 28]


@requires_pg
def test_enabling_an_anchored_cadence_anchors_it_today(pg, two_athletes):
    """Any other default ("the 1st") makes the first interval a partial
    one."""
    from app.services.fitness.coaching_jobs import get_schedule

    alice, _ = two_athletes
    _enable(pg, alice, "tape_measurement")
    schedule = get_schedule(pg, alice, "tape_measurement")
    assert schedule.anchor_date is not None
    assert schedule.cadence_days == 14


@requires_pg
def test_a_daily_cadence_fires_at_the_local_time(pg, two_athletes):
    from app.services.fitness.coaching_jobs import compute_next_due

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin", local_time=time(7, 0))
    after = datetime(2026, 6, 15, 10, 0, tzinfo=ET)
    due = compute_next_due(schedule, after=after)
    local = due.astimezone(ET)
    assert local.date() == date(2026, 6, 16)
    assert (local.hour, local.minute) == (7, 0)


@requires_pg
def test_the_skipped_dst_hour_still_fires_that_day(pg, two_athletes):
    """Spring forward: 02:30 does not exist on the switch day. Skipping the
    day entirely would silently drop one occurrence a year."""
    from app.services.fitness.coaching_jobs import compute_next_due

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin", local_time=time(2, 30))
    # 2026-03-08 is the US spring-forward date.
    after = datetime(2026, 3, 7, 12, 0, tzinfo=ET)
    due = compute_next_due(schedule, after=after)
    assert due is not None
    assert due.astimezone(ET).date() == date(2026, 3, 8)


@requires_pg
def test_the_repeated_dst_hour_fires_once(pg, two_athletes):
    """Autumn back: 01:30 happens twice. `fold=0` picks the first, and the
    occurrence ledger makes the second a duplicate claim rather than a
    second run."""
    from app.services.fitness.coaching_jobs import compute_next_due

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin", local_time=time(1, 30))
    # 2026-11-01 is the US fall-back date.
    after = datetime(2026, 10, 31, 12, 0, tzinfo=ET)
    due = compute_next_due(schedule, after=after)
    assert due is not None
    local = due.astimezone(ET)
    assert local.date() == date(2026, 11, 1)
    assert (local.hour, local.minute) == (1, 30)
    # The first of the two 01:30s: UTC offset -0400, not -0500.
    assert local.utcoffset() == timedelta(hours=-4)


@requires_pg
def test_a_disabled_cadence_has_no_due_time(pg, two_athletes):
    """Which is what keeps the sweep's partial index small."""
    from app.services.fitness.coaching_jobs import compute_next_due, set_schedule

    alice, _ = two_athletes
    schedule = set_schedule(pg, alice, "daily_checkin", enabled=False)
    pg.commit()
    assert compute_next_due(schedule) is None
    assert schedule.next_due_at is None


@requires_pg
def test_an_enabled_but_unconsented_cadence_has_no_due_time(pg, two_athletes):
    from app.services.fitness.coaching_jobs import set_schedule

    alice, _ = two_athletes
    schedule = set_schedule(pg, alice, "daily_checkin", enabled=True)
    pg.commit()
    assert schedule.consented is False
    assert schedule.next_due_at is None


# ─────────────────────────────────────────────────────────────────────────
# The sweep and the ledger
# ─────────────────────────────────────────────────────────────────────────

def _make_due(pg, schedule, *, minutes_ago=5):
    due = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    pg.execute(text("""
        UPDATE fitness_coaching_schedule SET next_due_at = :due WHERE id = :id
    """), {"due": due, "id": schedule.id})
    pg.commit()
    schedule.next_due_at = due
    return due


@requires_pg
def test_the_sweep_finds_only_due_enabled_consented_cadences(pg, two_athletes):
    from app.services.fitness.coaching_jobs import due_schedules, set_schedule

    alice, bob = two_athletes
    due_one = _enable(pg, alice, "daily_checkin")
    _make_due(pg, due_one)

    # Bob's is enabled but not consented.
    set_schedule(pg, bob, "daily_checkin", enabled=True)
    pg.commit()

    found = due_schedules(pg)
    ids = {s.id for s in found}
    assert due_one.id in ids
    assert all(s.user_id != bob for s in found)


@requires_pg
def test_a_snoozed_cadence_is_not_swept(pg, two_athletes):
    from app.services.fitness.coaching_jobs import due_schedules, snooze

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    snooze(pg, alice, "daily_checkin", datetime.now(UTC) + timedelta(days=3))
    pg.commit()

    assert all(s.id != schedule.id for s in due_schedules(pg))


@requires_pg
def test_claiming_an_occurrence_rolls_the_schedule_forward(pg, two_athletes):
    """Leaving `next_due_at` in the past makes every subsequent sweep
    re-examine the same row."""
    from app.services.fitness.coaching_jobs import claim_occurrence

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    due = _make_due(pg, schedule)

    occurrence = claim_occurrence(pg, schedule)
    pg.commit()
    assert occurrence is not None
    assert occurrence.occurrence_at == due.astimezone(UTC).replace(
        second=0, microsecond=0,
    )
    assert schedule.next_due_at > datetime.now(UTC)


@requires_pg
def test_two_sweeps_produce_exactly_one_occurrence(pg, two_athletes):
    """`DBScheduler` seeds UTC `last_run_at`, so a daily ET cron DOES fire
    twice (see test_db_scheduler_beat_double_fire.py). The ledger absorbing
    it into one artifact is the design, not a workaround."""
    from app.services.fitness.coaching_jobs import claim_occurrence, get_schedule

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)

    first = claim_occurrence(pg, schedule)
    pg.commit()
    # The second sweep re-reads the row, which now has a future due time.
    reread = get_schedule(pg, alice, "daily_checkin")
    reread.next_due_at = first.occurrence_at
    second = claim_occurrence(pg, reread)
    pg.commit()

    assert first is not None
    assert second is None, "the second sweep claimed the same occurrence again"
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coaching_job_run WHERE user_id = :u
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_the_unique_occurrence_index_is_enforced_by_the_database(pg, two_athletes):
    """Not by a "have we run yet" flag, which loses the race."""
    alice, _ = two_athletes
    from app.services.fitness.coaching_jobs import claim_occurrence

    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    occurrence = claim_occurrence(pg, schedule)
    pg.commit()

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coaching_job_run
                (id, user_id, kind, occurrence_at, status)
            VALUES (:id, :u, :k, :occ, 'claimed')
        """), {
            "id": str(uuid.uuid4()), "u": alice, "k": occurrence.kind,
            "occ": occurrence.occurrence_at,
        })
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_stale_claim_is_reclaimed_rather_than_lost(pg, two_athletes):
    """The enqueue-failed-and-died case. The claim row survives, which is
    why the claim is written BEFORE the enqueue — doing it the other way
    round loses the occurrence with no row to notice."""
    from app.services.fitness.coaching_jobs import (
        CLAIM_EXPIRY, claim_occurrence, get_schedule,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    first = claim_occurrence(pg, schedule)
    pg.commit()

    # The worker died between claiming and enqueueing.
    pg.execute(text("""
        UPDATE fitness_coaching_job_run SET claimed_at = :stale WHERE id = :id
    """), {"stale": datetime.now(UTC) - CLAIM_EXPIRY - timedelta(minutes=5),
           "id": first.run_id})
    pg.commit()

    reread = get_schedule(pg, alice, "daily_checkin")
    reread.next_due_at = first.occurrence_at
    second = claim_occurrence(pg, reread)
    pg.commit()

    assert second is not None
    assert second.reclaimed is True
    assert second.run_id == first.run_id, "a reclaim must not create a second row"
    attempts = pg.execute(text("""
        SELECT attempts FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": first.run_id}).scalar()
    assert attempts == 2


@requires_pg
def test_a_live_claim_is_not_reclaimed(pg, two_athletes):
    from app.services.fitness.coaching_jobs import claim_occurrence, get_schedule

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    first = claim_occurrence(pg, schedule)
    pg.commit()

    reread = get_schedule(pg, alice, "daily_checkin")
    reread.next_due_at = first.occurrence_at
    assert claim_occurrence(pg, reread) is None


@requires_pg
def test_a_completed_occurrence_is_never_reclaimed(pg, two_athletes):
    from app.services.fitness.coaching_jobs import (
        CLAIM_EXPIRY, claim_occurrence, complete_run, get_schedule,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    first = claim_occurrence(pg, schedule)
    complete_run(pg, alice, first.run_id)
    pg.execute(text("""
        UPDATE fitness_coaching_job_run SET claimed_at = :stale WHERE id = :id
    """), {"stale": datetime.now(UTC) - CLAIM_EXPIRY * 2, "id": first.run_id})
    pg.commit()

    reread = get_schedule(pg, alice, "daily_checkin")
    reread.next_due_at = first.occurrence_at
    assert claim_occurrence(pg, reread) is None


@requires_pg
def test_a_long_overdue_occurrence_expires_rather_than_running(pg, two_athletes):
    """A check-in nudge for last Tuesday is not a nudge, it is confusing."""
    from app.services.fitness.coaching_jobs import (
        OCCURRENCE_GRACE, claim_occurrence,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule,
              minutes_ago=int(OCCURRENCE_GRACE.total_seconds() / 60) + 120)

    assert claim_occurrence(pg, schedule) is None
    pg.commit()
    row = pg.execute(text("""
        SELECT status, noop_reason FROM fitness_coaching_job_run
        WHERE user_id = :u
    """), {"u": alice}).fetchone()
    assert row.status == "noop"
    assert row.noop_reason == "occurrence_expired"
    # And it rolled forward, so it does not retry forever.
    assert schedule.next_due_at > datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────
# Dispatch is not completion
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_claiming_records_evaluation_not_completion(pg, two_athletes):
    """`DBScheduler` marks `last_status='success'` at DISPATCH time, so a
    green row proves nothing about the work. This subsystem refuses to repeat
    that: looking at a cadence and completing its work are separate fields."""
    from app.services.fitness.coaching_jobs import claim_occurrence, get_schedule

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    claim_occurrence(pg, schedule)
    pg.commit()

    reread = get_schedule(pg, alice, "daily_checkin")
    assert reread.last_evaluated_at is not None
    assert reread.last_completed_at is None


@requires_pg
def test_completing_a_run_stamps_the_schedule(pg, two_athletes):
    from app.services.fitness.coaching_jobs import (
        claim_occurrence, complete_run, get_schedule,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    occurrence = claim_occurrence(pg, schedule)
    complete_run(pg, alice, occurrence.run_id)
    pg.commit()

    assert get_schedule(pg, alice, "daily_checkin").last_completed_at is not None
    row = pg.execute(text("""
        SELECT status FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).fetchone()
    assert row.status == "completed"


@requires_pg
def test_a_preference_change_after_the_claim_makes_the_run_a_noop(
    pg, two_athletes,
):
    """An occurrence claimed at 06:58 must not run at 07:00 if the athlete
    switched the cadence off at 06:59."""
    from app.services.fitness.coaching_jobs import (
        begin_run, claim_occurrence, set_schedule,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    occurrence = claim_occurrence(pg, schedule)
    pg.commit()

    set_schedule(pg, alice, "daily_checkin", enabled=False)
    pg.commit()

    assert begin_run(pg, alice, occurrence.run_id) is None
    pg.commit()
    row = pg.execute(text("""
        SELECT status, noop_reason FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).fetchone()
    assert row.status == "noop"
    assert row.noop_reason == "cadence_disabled_since_claim"


@requires_pg
def test_a_snooze_after_the_claim_makes_the_run_a_noop(pg, two_athletes):
    from app.services.fitness.coaching_jobs import (
        begin_run, claim_occurrence, snooze,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    occurrence = claim_occurrence(pg, schedule)
    snooze(pg, alice, "daily_checkin", datetime.now(UTC) + timedelta(days=2))
    pg.commit()

    assert begin_run(pg, alice, occurrence.run_id) is None
    pg.commit()
    reason = pg.execute(text("""
        SELECT noop_reason FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).scalar()
    assert reason in ("snoozed_since_claim", "preference_changed_since_claim")


@requires_pg
def test_a_noop_always_records_why(pg, two_athletes):
    """"Nothing happened" with no reason is indistinguishable from a bug, and
    "why didn't Sara say anything" would have no answer."""
    alice, _ = two_athletes
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coaching_job_run
                (id, user_id, kind, occurrence_at, status)
            VALUES (:id, :u, 'daily_checkin', NOW(), 'noop')
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_failed_run_always_records_a_category(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coaching_job_run
                (id, user_id, kind, occurrence_at, status)
            VALUES (:id, :u, 'daily_checkin', NOW(), 'failed')
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_terminal_run_is_not_overwritten(pg, two_athletes):
    from app.services.fitness.coaching_jobs import (
        claim_occurrence, complete_run, fail_run,
    )

    alice, _ = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    occurrence = claim_occurrence(pg, schedule)
    complete_run(pg, alice, occurrence.run_id)
    fail_run(pg, alice, occurrence.run_id, category="too_late")
    pg.commit()

    status = pg.execute(text("""
        SELECT status FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).scalar()
    assert status == "completed"


# ─────────────────────────────────────────────────────────────────────────
# Ownership
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_run_cannot_hang_off_another_athletes_schedule(pg, two_athletes):
    """An FK to a UUID alone does not enforce ownership (§5), and this one
    would act on one athlete's cadence under another's id."""
    alice, bob = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coaching_job_run
                (id, user_id, schedule_id, kind, occurrence_at, status)
            VALUES (:id, :u, :sid, 'daily_checkin', NOW(), 'claimed')
        """), {"id": str(uuid.uuid4()), "u": bob, "sid": schedule.id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_one_athlete_cannot_read_anothers_runs(pg, two_athletes):
    from app.services.fitness.coaching_jobs import claim_occurrence, recent_runs

    alice, bob = two_athletes
    schedule = _enable(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    claim_occurrence(pg, schedule)
    pg.commit()

    assert recent_runs(pg, bob) == []
    assert len(recent_runs(pg, alice)) == 1


@requires_pg
def test_one_athlete_cannot_snooze_anothers_cadence(pg, two_athletes):
    from app.services.fitness.coaching_jobs import snooze

    alice, bob = two_athletes
    _enable(pg, alice, "daily_checkin")
    with pytest.raises(LookupError):
        snooze(pg, bob, "daily_checkin", datetime.now(UTC) + timedelta(days=1))


@requires_pg
def test_the_cadence_service_refuses_a_missing_owner(pg):
    from app.services.fitness.coaching_jobs import list_schedules, set_schedule
    from app.services.fitness.data_access import FitnessDataError

    for bad in ("", None, "  "):
        with pytest.raises((FitnessDataError, ValueError)):
            list_schedules(pg, bad)
        with pytest.raises((FitnessDataError, ValueError)):
            set_schedule(pg, bad, "daily_checkin", enabled=True)


# ─────────────────────────────────────────────────────────────────────────
# The global sweep cannot be hijacked
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_there_is_exactly_one_global_sweep_row(pg):
    """Per-athlete `scheduled_job` rows would put `task_name` behind a
    user-facing API, which is arbitrary code execution with extra steps."""
    rows = pg.execute(text("""
        SELECT key, task_name, queue, enabled, editable, source
        FROM scheduled_job
        WHERE task_name = 'app.tasks.fitness_coach.sweep_due_occurrences'
    """)).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row.key == "fitness_coaching_due_sweep"
    assert row.queue == "health"
    assert row.enabled is True
    # Not editable from the settings UI: it is plumbing, not a preference.
    assert row.editable is False
    assert row.source == "system"


@requires_pg
def test_the_cadence_table_has_no_task_or_queue_column(pg):
    """The structural guarantee. An athlete's row cannot name a task because
    there is nowhere to put one."""
    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'fitness_coaching_schedule'
    """)).fetchall()}
    for forbidden in ("task_name", "queue", "args", "kwargs", "task",
                      "expires_seconds", "cron_expr"):
        assert forbidden not in columns, f"{forbidden} is athlete-writable"


def test_the_task_mapping_lives_in_code():
    from app.services.fitness.coaching_jobs import CADENCE_KINDS, KIND_TASKS

    for kind in CADENCE_KINDS:
        assert kind in KIND_TASKS, kind
        assert KIND_TASKS[kind].startswith("app.tasks.fitness_coach."), kind


def test_the_cadence_patch_schema_rejects_a_task_name():
    """`extra="forbid"`, so an attempt to send one is a 422 rather than
    something silently ignored."""
    from pydantic import ValidationError
    from app.routes.fitness_coach import CadencePatch

    with pytest.raises(ValidationError):
        CadencePatch(task_name="app.tasks.evil.do_it")
    with pytest.raises(ValidationError):
        CadencePatch(queue="critical")
    with pytest.raises(ValidationError):
        CadencePatch(user_id="somebody-else")
    with pytest.raises(ValidationError):
        CadencePatch(kwargs={"user_id": "somebody-else"})


def test_the_sweep_batch_is_bounded():
    """A backlog after an outage must not enqueue a thousand model calls in
    one tick."""
    from app.services.fitness.coaching_jobs import SWEEP_BATCH_SIZE
    assert 1 <= SWEEP_BATCH_SIZE <= 100


# ─────────────────────────────────────────────────────────────────────────
# The HTTP boundary
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.fitness_coach import router

    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    return TestClient(app)


def _bearer(user_id: str) -> dict:
    from app.core.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}


@requires_pg
def test_the_api_lists_every_cadence_as_off(pg, two_athletes, client):
    alice, _ = two_athletes
    response = client.get("/api/fitness/coach/cadences", headers=_bearer(alice))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 6
    assert all(row["enabled"] is False for row in body)
    assert all(row["consented"] is False for row in body)


@requires_pg
def test_the_api_enables_one_cadence(pg, two_athletes, client):
    alice, _ = two_athletes
    response = client.patch(
        "/api/fitness/coach/cadences/weekly_review",
        headers=_bearer(alice),
        json={"enabled": True, "consented": True, "local_time": "07:30",
              "weekdays": [1]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True and body["consented"] is True
    assert body["local_time"] == "07:30"
    assert body["next_due_at"] is not None


@requires_pg
def test_the_api_refuses_a_task_name(pg, two_athletes, client):
    """The completion criterion: global schedule configuration cannot be
    hijacked through athlete settings."""
    alice, _ = two_athletes
    for payload in (
        {"task_name": "app.tasks.evil.run"},
        {"queue": "critical"},
        {"user_id": "somebody-else"},
        {"cron_expr": "* * * * *"},
    ):
        response = client.patch(
            "/api/fitness/coach/cadences/daily_checkin",
            headers=_bearer(alice), json={"enabled": True, **payload},
        )
        assert response.status_code == 422, payload

    # And nothing was written.
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coaching_schedule WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_the_api_cannot_touch_the_global_sweep_row(pg, two_athletes, client):
    """There is no route here that writes `scheduled_job` at all."""
    alice, _ = two_athletes
    before = pg.execute(text("""
        SELECT enabled, task_name, queue FROM scheduled_job
        WHERE key = 'fitness_coaching_due_sweep'
    """)).fetchone()

    client.patch(
        "/api/fitness/coach/cadences/daily_checkin",
        headers=_bearer(alice), json={"enabled": True, "consented": True},
    )
    after = pg.execute(text("""
        SELECT enabled, task_name, queue FROM scheduled_job
        WHERE key = 'fitness_coaching_due_sweep'
    """)).fetchone()
    assert (after.enabled, after.task_name, after.queue) == \
        (before.enabled, before.task_name, before.queue)


@requires_pg
def test_an_unauthenticated_request_cannot_change_a_cadence(client):
    assert client.get("/api/fitness/coach/cadences").status_code in (401, 403)
    assert client.patch(
        "/api/fitness/coach/cadences/daily_checkin", json={"enabled": True},
    ).status_code in (401, 403)


@requires_pg
def test_the_api_rejects_an_unknown_kind(pg, two_athletes, client):
    alice, _ = two_athletes
    response = client.patch(
        "/api/fitness/coach/cadences/nag_me_constantly",
        headers=_bearer(alice), json={"enabled": True},
    )
    assert response.status_code == 422


@requires_pg
def test_the_api_reports_a_version_conflict_with_the_current_version(
    pg, two_athletes, client,
):
    alice, _ = two_athletes
    first = client.patch(
        "/api/fitness/coach/cadences/daily_checkin",
        headers=_bearer(alice), json={"enabled": True, "consented": True},
    ).json()
    response = client.patch(
        "/api/fitness/coach/cadences/daily_checkin",
        headers=_bearer(alice),
        json={"enabled": False, "expected_version": first["version"] - 1},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["current_version"] == first["version"]


@requires_pg
def test_the_api_shows_what_each_occurrence_actually_did(pg, two_athletes, client):
    """A green `scheduled_job` row proves the sweep was dispatched and
    nothing more. These rows are the record of the work."""
    from app.services.fitness.coaching_jobs import (
        claim_occurrence, get_schedule, noop_run,
    )

    alice, _ = two_athletes
    _enable(pg, alice, "daily_checkin")
    schedule = get_schedule(pg, alice, "daily_checkin")
    _make_due(pg, schedule)
    occurrence = claim_occurrence(pg, schedule)
    noop_run(pg, alice, occurrence.run_id, "nothing_missing")
    pg.commit()

    response = client.get(
        "/api/fitness/coach/cadences/daily_checkin/runs",
        headers=_bearer(alice),
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "noop"
    assert rows[0]["noop_reason"] == "nothing_missing"
