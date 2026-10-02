"""Step 10 of FITNESS_COACH_IMPLEMENTATION_PLAN: tape measurements work
through one schema, add nothing to the body-observation authority, and only
compare what is actually comparable.

The requirement that shapes the design: **a new thing to measure must not
need a migration.** A column per circumference gives you `waist_cm`,
`chest_cm`, `left_arm_cm`, … and then cannot hold "forearm at the widest
point, standing" without a deploy.

The requirement that shapes the comparisons: a waist measured at the navel
and a waist measured at the narrowest point differ by centimetres, and that
difference is not a change in the athlete.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_measurements_pg.py
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
    alice = f"m5a-{uuid.uuid4().hex[:18]}"
    bob = f"m5b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m5.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for t in ("health_metric", "fitness_measurement_period",
              "fitness_athlete_profile", "daily_recovery_log", "weight_trend"):
        pg.execute(text(f"DELETE FROM {t} WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
    pg.execute(text("""
        DELETE FROM fitness_measurement_type WHERE owner_user_id = ANY(:ids)
    """), {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _log(pg, user_id, **kwargs):
    from app.schemas.fitness_coach import MeasurementIn
    from app.services.fitness.observations import log_measurement
    return log_measurement(pg, user_id, MeasurementIn(**kwargs))


# ─────────────────────────────────────────────────────────────────────────
# One authority for body numbers
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_there_is_no_second_table_holding_measured_values(pg):
    """§4.2: body observations have one authority.

    A second numeric store could immediately disagree with `health_metric` —
    most obviously about bodyweight, which is both a tape-session reading and
    a `weight` observation.
    """
    tables = {r[0] for r in pg.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE 'fitness_%measurement%'
    """)).fetchall()}
    assert tables == {"fitness_measurement_type", "fitness_measurement_period"}, (
        f"an extra measurement table exists: {tables}"
    )

    # Neither descriptor table holds a measured number.
    for table in tables:
        columns = {r[0] for r in pg.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = :t
        """), {"t": table}).fetchall()}
        assert "value" not in columns, f"{table} holds a measured value"


@requires_pg
def test_a_reading_is_stored_as_a_canonical_observation(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    alice, _ = two_athletes

    out = _log(pg, alice, type_code="waist_circumference", value=81.5,
               unit=Unit.CM, measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
               side=Side.NONE)

    assert out.value == 81.5
    assert out.unit is Unit.CM
    row = pg.execute(text("""
        SELECT metric_type, value, unit, measurement_type_code, metadata, logical_date
        FROM health_metric WHERE id = :id
    """), {"id": out.id}).fetchone()
    assert row.metric_type == "measurement:waist_circumference"
    assert float(row.value) == 81.5
    assert row.unit == "cm"
    # The generated column makes "every waist reading" an index scan rather
    # than a JSONB filter over the athlete's whole observation history.
    assert row.measurement_type_code == "waist_circumference"
    assert row.metadata["label"] == "Waist"
    assert row.logical_date == date(2026, 10, 1)


@requires_pg
def test_bodyweight_is_not_duplicated_as_a_tape_metric(pg, two_athletes):
    """Weight is `weight`, not `measurement:bodyweight`.

    A tape-session copy of bodyweight would be a second answer to "what did
    I weigh on 1 October".
    """
    types = {
        r[0] for r in pg.execute(text(
            "SELECT code FROM fitness_measurement_type WHERE owner_user_id IS NULL"
        )).fetchall()
    }
    for forbidden in ("weight", "bodyweight", "body_weight", "body_mass"):
        assert forbidden not in types, (
            f"{forbidden} is seeded as a tape metric; bodyweight already has "
            "an authority in health_metric"
        )


# ─────────────────────────────────────────────────────────────────────────
# Custom types without a migration
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_custom_type_can_be_created_and_logged_with_no_migration(pg, two_athletes):
    """The central requirement of Step 10."""
    from app.schemas.fitness_coach import (
        MeasurementTypeIn, Quantity, Side, Unit,
    )
    from app.services.fitness.observations import create_measurement_type

    alice, _ = two_athletes
    before = pg.execute(text("SELECT version_num FROM alembic_version")).scalar()

    created = create_measurement_type(pg, alice, MeasurementTypeIn(
        code="Forearm At Widest, Standing", label="Forearm (standing)",
        quantity=Quantity.LENGTH, canonical_unit=Unit.CM, allows_side=True,
        protocol_guidance="Standing, arm hanging relaxed, tape at the widest point.",
    ))
    assert created.code == "forearm_at_widest_standing", (
        "the code is normalized by the same function exercise aliases use"
    )
    assert created.owner_user_id == alice

    out = _log(pg, alice, type_code=created.code, value=31.5, unit=Unit.CM,
               measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
               side=Side.LEFT)
    assert out.value == 31.5

    after = pg.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert before == after, "adding a measurement type must not need a migration"


@requires_pg
def test_a_custom_type_is_private_to_its_owner(pg, two_athletes):
    """Its label is something the athlete wrote."""
    from app.schemas.fitness_coach import MeasurementTypeIn, Quantity, Unit
    from app.services.fitness.observations import (
        create_measurement_type, list_measurement_types,
    )

    alice, bob = two_athletes
    create_measurement_type(pg, alice, MeasurementTypeIn(
        code="shoulder_width_for_the_jacket", label="Shoulders (jacket)",
        quantity=Quantity.LENGTH, canonical_unit=Unit.CM,
    ))

    alice_codes = {t.code for t in list_measurement_types(pg, alice)}
    bob_codes = {t.code for t in list_measurement_types(pg, bob)}
    assert "shoulder_width_for_the_jacket" in alice_codes
    assert "shoulder_width_for_the_jacket" not in bob_codes
    # Both still see the global seeds.
    assert "waist_circumference" in alice_codes and "waist_circumference" in bob_codes


@requires_pg
def test_bob_cannot_log_against_alices_custom_type(pg, two_athletes):
    """404-shaped, so a private code cannot even be probed for."""
    from app.schemas.fitness_coach import MeasurementTypeIn, Quantity, Unit
    from app.services.fitness.observations import create_measurement_type

    alice, bob = two_athletes
    created = create_measurement_type(pg, alice, MeasurementTypeIn(
        code="alices_odd_measure", label="Odd", quantity=Quantity.LENGTH,
        canonical_unit=Unit.CM,
    ))
    with pytest.raises(LookupError):
        _log(pg, bob, type_code=created.code, value=30.0, unit=Unit.CM,
             measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET))
    pg.rollback()


@requires_pg
def test_two_athletes_may_use_the_same_custom_code(pg, two_athletes):
    """The per-athlete namespace is separate."""
    from app.schemas.fitness_coach import MeasurementTypeIn, Quantity, Unit
    from app.services.fitness.observations import create_measurement_type

    alice, bob = two_athletes
    for uid in (alice, bob):
        created = create_measurement_type(pg, uid, MeasurementTypeIn(
            code="my_own_thing", label="Mine", quantity=Quantity.LENGTH,
            canonical_unit=Unit.CM,
        ))
        assert created.owner_user_id == uid
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_measurement_type WHERE code = 'my_own_thing'
    """)).scalar() == 2


@requires_pg
def test_a_custom_code_cannot_shadow_a_global_seed(pg, two_athletes):
    """Two `waist_circumference` definitions with different protocols would
    make the athlete's own history incomparable with itself."""
    from app.schemas.fitness_coach import MeasurementTypeIn, Quantity, Unit
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.observations import create_measurement_type

    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        create_measurement_type(pg, alice, MeasurementTypeIn(
            code="waist_circumference", label="My waist",
            quantity=Quantity.LENGTH, canonical_unit=Unit.CM,
        ))
    assert "global" in str(e.value)
    pg.rollback()


@requires_pg
def test_duplicating_your_own_code_is_refused(pg, two_athletes):
    from app.schemas.fitness_coach import MeasurementTypeIn, Quantity, Unit
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.observations import create_measurement_type

    alice, _ = two_athletes
    payload = MeasurementTypeIn(code="twice", label="Twice",
                                quantity=Quantity.LENGTH, canonical_unit=Unit.CM)
    create_measurement_type(pg, alice, payload)
    with pytest.raises(FitnessDataError):
        create_measurement_type(pg, alice, payload)
    pg.rollback()


@requires_pg
def test_the_unique_index_enforces_the_namespaces(pg, two_athletes):
    """Belt and braces: the service refuses, and so does the database."""
    alice, _ = two_athletes
    for owner in (None, alice):
        code = f"idx-test-{uuid.uuid4().hex[:8]}"
        for attempt in range(2):
            try:
                pg.execute(text("""
                    INSERT INTO fitness_measurement_type
                        (id, code, label, quantity, canonical_unit, owner_user_id)
                    VALUES (:id, :code, 'X', 'length', 'cm', :owner)
                """), {"id": str(uuid.uuid4()), "code": code, "owner": owner})
                pg.commit()
                assert attempt == 0, "the second insert should have been refused"
            except IntegrityError:
                assert attempt == 1
                pg.rollback()
        pg.execute(text("DELETE FROM fitness_measurement_type WHERE code = :c"),
                   {"c": code})
        pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Sides and sites
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_left_and_right_are_separate_series(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.observations import list_measurements
    alice, _ = two_athletes

    _log(pg, alice, type_code="upper_arm_circumference", value=38.5, unit=Unit.CM,
         measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.LEFT)
    _log(pg, alice, type_code="upper_arm_circumference", value=39.2, unit=Unit.CM,
         measured_at=datetime(2026, 10, 1, 7, 1, tzinfo=ET), side=Side.RIGHT)

    readings = list_measurements(pg, alice, type_code="upper_arm_circumference")
    by_side = {r.side.value: r.value for r in readings}
    assert by_side == {"left": 38.5, "right": 39.2}


@requires_pg
def test_a_side_is_required_for_a_sided_type(pg, two_athletes):
    """Two readings of different arms with no side would look like a change."""
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        _log(pg, alice, type_code="upper_arm_circumference", value=38.5,
             unit=Unit.CM, measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
             side=Side.NONE)
    assert "which one" in str(e.value)
    pg.rollback()


@requires_pg
def test_a_side_is_refused_for_an_unsided_type(pg, two_athletes):
    """A waist has no sides; a "left waist" would split one series into two."""
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        _log(pg, alice, type_code="waist_circumference", value=81.5, unit=Unit.CM,
             measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.LEFT)
    assert "no left/right distinction" in str(e.value)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Units
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_inches_are_converted_to_the_types_canonical_centimetres(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    alice, _ = two_athletes
    out = _log(pg, alice, type_code="waist_circumference", value=32.0,
               unit=Unit.INCH, measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
               side=Side.NONE)
    assert out.unit is Unit.CM
    assert out.value == pytest.approx(81.28)

    meta = pg.execute(text("SELECT metadata FROM health_metric WHERE id = :id"),
                      {"id": out.id}).scalar()
    assert meta["entered_as"] == {"value": 32.0, "unit": "in"}, (
        "what the athlete typed is preserved, so the conversion is reversible"
    )


@requires_pg
def test_an_incompatible_unit_is_refused(pg, two_athletes):
    """A kilogram is not a circumference."""
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        _log(pg, alice, type_code="waist_circumference", value=81.5, unit=Unit.KG,
             measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.NONE)
    assert "cannot be converted" in str(e.value)
    pg.rollback()


@requires_pg
@pytest.mark.parametrize("bad", [0, -3, float("nan"), float("inf")])
def test_nonpositive_and_nonfinite_values_are_refused(pg, two_athletes, bad):
    from app.schemas.fitness_coach import MeasurementIn, Unit
    alice, _ = two_athletes
    with pytest.raises(Exception):
        MeasurementIn(type_code="waist_circumference", value=bad, unit=Unit.CM,
                      measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET))


@requires_pg
def test_a_measurement_must_state_its_unit(pg, two_athletes):
    from app.schemas.fitness_coach import MeasurementIn, Unit
    with pytest.raises(Exception):
        MeasurementIn(type_code="waist_circumference", value=81.5,
                      unit=Unit.UNKNOWN,
                      measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET))


# ─────────────────────────────────────────────────────────────────────────
# Periods
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_period_groups_one_tape_session(pg, two_athletes):
    from app.schemas.fitness_coach import (
        MeasurementPeriodIn, Side, Unit,
    )
    from app.services.fitness.observations import (
        create_measurement_period, list_measurements,
    )

    alice, _ = two_athletes
    period = create_measurement_period(pg, alice, MeasurementPeriodIn(
        measured_on=date(2026, 10, 1),
        protocol="Morning, fasted, before water.",
        photo_period_label="2026-10 front/side/back",
    ))

    for code, value, side in (
        ("waist_circumference", 81.5, Side.NONE),
        ("chest_circumference", 104.0, Side.NONE),
        ("upper_arm_circumference", 38.5, Side.LEFT),
    ):
        _log(pg, alice, type_code=code, value=value, unit=Unit.CM,
             measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
             side=side, period_id=period.id)

    readings = list_measurements(pg, alice)
    assert len(readings) == 3
    assert all(r.period_id == period.id for r in readings), (
        "three readings from one sitting must be one sitting"
    )
    assert all(r.protocol == "Morning, fasted, before water." for r in readings)


@requires_pg
def test_a_foreign_period_is_refused(pg, two_athletes):
    from app.schemas.fitness_coach import MeasurementPeriodIn, Side, Unit
    from app.services.fitness.observations import create_measurement_period

    alice, bob = two_athletes
    bobs_period = create_measurement_period(pg, bob, MeasurementPeriodIn(
        measured_on=date(2026, 10, 1),
    ))
    with pytest.raises(LookupError):
        _log(pg, alice, type_code="waist_circumference", value=81.5, unit=Unit.CM,
             measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
             side=Side.NONE, period_id=bobs_period.id)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Corrections and comparability
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_corrected_reading_supersedes_and_is_excluded(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.observations import list_measurements
    alice, _ = two_athletes

    wrong = _log(pg, alice, type_code="waist_circumference", value=8.15,
                 unit=Unit.CM, measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
                 side=Side.NONE)
    right = _log(pg, alice, type_code="waist_circumference", value=81.5,
                 unit=Unit.CM, measured_at=datetime(2026, 10, 1, 7, 5, tzinfo=ET),
                 side=Side.NONE, corrects_observation_id=wrong.id)

    live = list_measurements(pg, alice, type_code="waist_circumference")
    assert [r.value for r in live] == [81.5]

    with_history = list_measurements(
        pg, alice, type_code="waist_circumference", include_superseded=True,
    )
    assert len(with_history) == 2, "the original reading is retained"
    superseded = next(r for r in with_history if r.id == wrong.id)
    assert superseded.superseded_by_id == right.id


@requires_pg
def test_a_change_needs_two_comparable_readings(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unavailable, Unit
    from app.services.fitness.observations import measurement_change
    alice, _ = two_athletes

    none_yet = measurement_change(pg, alice, "waist_circumference")
    assert none_yet.value is None
    assert none_yet.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE

    _log(pg, alice, type_code="waist_circumference", value=83.0, unit=Unit.CM,
         measured_at=datetime(2026, 9, 1, 7, 0, tzinfo=ET), side=Side.NONE)
    one_only = measurement_change(pg, alice, "waist_circumference")
    assert one_only.value is None, "one reading cannot state a change"
    assert one_only.observed_days == 1 and one_only.expected_days == 2


@requires_pg
def test_a_change_between_comparable_readings_reports_elapsed_days(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.observations import measurement_change
    alice, _ = two_athletes

    _log(pg, alice, type_code="waist_circumference", value=83.0, unit=Unit.CM,
         measured_at=datetime(2026, 9, 1, 7, 0, tzinfo=ET), side=Side.NONE,
         protocol="navel")
    _log(pg, alice, type_code="waist_circumference", value=81.5, unit=Unit.CM,
         measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.NONE,
         protocol="navel")

    change = measurement_change(pg, alice, "waist_circumference")
    assert change.value == pytest.approx(-1.5)
    assert change.unit is Unit.CM
    assert "30 days apart" in change.note


@requires_pg
def test_readings_taken_under_different_protocols_are_not_comparable(pg, two_athletes):
    """A waist at the navel and a waist at the narrowest point differ by
    centimetres, and that difference is not a change in the athlete."""
    from app.schemas.fitness_coach import Side, Unavailable, Unit
    from app.services.fitness.observations import measurement_change
    alice, _ = two_athletes

    _log(pg, alice, type_code="waist_circumference", value=83.0, unit=Unit.CM,
         measured_at=datetime(2026, 9, 1, 7, 0, tzinfo=ET), side=Side.NONE,
         protocol="at the navel")
    _log(pg, alice, type_code="waist_circumference", value=79.0, unit=Unit.CM,
         measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.NONE,
         protocol="at the narrowest point")

    change = measurement_change(pg, alice, "waist_circumference")
    assert change.value is None
    assert change.unavailable_reason is Unavailable.NOT_COMPARABLE
    assert "different protocols" in change.note


@requires_pg
def test_a_change_is_computed_per_side(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.observations import measurement_change
    alice, _ = two_athletes

    for when, left, right in (
        (datetime(2026, 9, 1, 7, 0, tzinfo=ET), 38.0, 38.8),
        (datetime(2026, 10, 1, 7, 0, tzinfo=ET), 38.6, 39.0),
    ):
        _log(pg, alice, type_code="upper_arm_circumference", value=left,
             unit=Unit.CM, measured_at=when, side=Side.LEFT, protocol="relaxed")
        _log(pg, alice, type_code="upper_arm_circumference", value=right,
             unit=Unit.CM, measured_at=when + timedelta(minutes=1),
             side=Side.RIGHT, protocol="relaxed")

    left_change = measurement_change(pg, alice, "upper_arm_circumference",
                                     side="left")
    right_change = measurement_change(pg, alice, "upper_arm_circumference",
                                      side="right")
    assert left_change.value == pytest.approx(0.6)
    assert right_change.value == pytest.approx(0.2)


@requires_pg
def test_measurements_do_not_cross_between_athletes(pg, two_athletes):
    from app.schemas.fitness_coach import Side, Unit
    from app.services.fitness.observations import list_measurements
    alice, bob = two_athletes

    _log(pg, alice, type_code="waist_circumference", value=81.5, unit=Unit.CM,
         measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.NONE)
    _log(pg, bob, type_code="waist_circumference", value=96.0, unit=Unit.CM,
         measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), side=Side.NONE)

    assert [r.value for r in list_measurements(pg, alice)] == [81.5]
    assert [r.value for r in list_measurements(pg, bob)] == [96.0]


# ─────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_measurement_api_round_trip(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, bob = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    a = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}
    b = {"Authorization": f"Bearer {create_access_token({'sub': bob})}"}

    assert client.get("/api/fitness/coach/measurement-types").status_code == 401

    types = client.get("/api/fitness/coach/measurement-types", headers=a)
    assert types.status_code == 200
    codes = {t["code"] for t in types.json()}
    assert "waist_circumference" in codes
    waist = next(t for t in types.json() if t["code"] == "waist_circumference")
    assert waist["owner_user_id"] is None
    assert waist["allows_side"] is False
    assert "navel" in (waist["protocol_guidance"] or "")

    # A custom type, with no migration.
    r = client.post("/api/fitness/coach/measurement-types", headers=a, json={
        "code": "Shoulder Width", "label": "Shoulders",
        "quantity": "length", "canonical_unit": "cm",
    })
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "shoulder_width"

    # Duplicating it is a 409, not a silent second row.
    assert client.post("/api/fitness/coach/measurement-types", headers=a, json={
        "code": "shoulder_width", "label": "Shoulders again",
        "quantity": "length", "canonical_unit": "cm",
    }).status_code == 409

    # A period.
    r = client.post("/api/fitness/coach/measurement-periods", headers=a, json={
        "measured_on": "2026-10-01", "protocol": "Morning, fasted.",
    })
    assert r.status_code == 201, r.text
    period_id = r.json()["id"]

    # A reading.
    r = client.post("/api/fitness/coach/measurements", headers=a, json={
        "type_code": "waist_circumference", "value": 81.5, "unit": "cm",
        "measured_at": "2026-10-01T11:00:00+00:00", "side": "none",
        "period_id": period_id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "Waist"

    listing = client.get("/api/fitness/coach/measurements", headers=a,
                         params={"type_code": "waist_circumference"})
    assert listing.status_code == 200
    assert [m["value"] for m in listing.json()] == [81.5]

    # Bob's listing is empty, and he cannot use Alice's period.
    assert client.get("/api/fitness/coach/measurements", headers=b).json() == []
    assert client.post("/api/fitness/coach/measurements", headers=b, json={
        "type_code": "waist_circumference", "value": 96.0, "unit": "cm",
        "measured_at": "2026-10-01T11:00:00+00:00", "side": "none",
        "period_id": period_id,
    }).status_code == 404

    # A side on an unsided type is a 422 with a reason.
    bad = client.post("/api/fitness/coach/measurements", headers=a, json={
        "type_code": "waist_circumference", "value": 81.5, "unit": "cm",
        "measured_at": "2026-10-02T11:00:00+00:00", "side": "left",
    })
    assert bad.status_code == 422
    assert "no left/right distinction" in bad.text

    # An unknown type is a 404.
    assert client.post("/api/fitness/coach/measurements", headers=a, json={
        "type_code": "made_up", "value": 10.0, "unit": "cm",
        "measured_at": "2026-10-02T11:00:00+00:00",
    }).status_code == 404

    # The change endpoint explains itself when it cannot answer.
    change = client.get(
        "/api/fitness/coach/measurements/waist_circumference/change", headers=a,
    )
    assert change.status_code == 200
    assert change.json()["value"] is None
    assert change.json()["unavailable_reason"] == "insufficient_coverage"


@requires_pg
def test_the_api_caps_a_date_span(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    r = client.get("/api/fitness/coach/measurements", headers=headers, params={
        "start_date": "2015-01-01", "end_date": "2026-01-01",
    })
    assert r.status_code == 422, "an unbounded span must be refused"
    assert "cap" in r.text or "exceeds" in r.text
