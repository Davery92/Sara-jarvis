from datetime import datetime, timedelta, timezone

import pytest

from app.services.location_service import process_report
from app.services.situational_signals import _guidance_for_office_state


@pytest.mark.asyncio
@pytest.mark.parametrize("offset_minutes", [None, -11, +2])
async def test_stale_or_future_location_report_is_ignored_before_database_work(offset_minutes):
    # The offset is turned into an instant HERE, not in the parametrize list.
    #
    # It used to be `datetime.now(timezone.utc) + timedelta(minutes=2)` in the
    # decorator, which is evaluated once at MODULE IMPORT — i.e. at collection.
    # Once the suite took longer than two minutes to reach this test, that value
    # was no longer in the future and not yet stale (the staleness window is ten
    # minutes), so the guard under test did not fire, execution reached
    # `classify(db, ...)` with the deliberately-None db, and the test failed with
    # `AttributeError: 'NoneType' object has no attribute 'execute'`.
    #
    # Found 2026-09-29 by controlled-clock comparison (the reliable-assistant
    # correction required one): the same test passed in the 2026-09-24 snapshot
    # and failed in the candidate in the same minute, and passed in BOTH when run
    # alone. The difference was suite duration, not source. Demonstrated directly
    # by calling `process_report` with that same instant once two minutes had
    # passed — same AttributeError, on unmodified product code.
    observed_at = (
        None if offset_minutes is None
        else datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    )
    result = await process_report(
        None,
        "user-1",
        40.0,
        -75.0,
        10.0,
        "test",
        observed_at=observed_at,
    )

    assert result == {"classified_place": None, "ignored": "stale_sample"}


def test_office_attendance_is_unknown_without_a_configured_office():
    guidance = _guidance_for_office_state(False)

    assert "Treat office attendance as unknown" in guidance
    assert "You're not at the office" not in guidance


def test_office_specific_guidance_requires_a_configured_office():
    guidance = _guidance_for_office_state(True)

    assert "You're not at the office" in guidance
