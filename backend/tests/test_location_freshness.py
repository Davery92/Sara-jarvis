from datetime import datetime, timedelta, timezone

import pytest

from app.services.location_service import process_report
from app.services.situational_signals import _guidance_for_office_state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observed_at",
    [
        None,
        datetime.now(timezone.utc) - timedelta(minutes=11),
        datetime.now(timezone.utc) + timedelta(minutes=2),
    ],
)
async def test_stale_or_future_location_report_is_ignored_before_database_work(observed_at):
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
