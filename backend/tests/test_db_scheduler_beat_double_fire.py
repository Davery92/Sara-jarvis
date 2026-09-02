"""Phase 1 of NOTIFICATION_DELIVERY_FIX_PLAN_2026_08_17: beat double-fire.

DBScheduler._reload() used to seed entry.last_run_at straight from the DB's
UTC-aware timestamptz. celery's crontab.is_due() does its calendar-field
arithmetic in that datetime's own tz frame, so a `0 6 * * *` ET schedule with
a UTC-aware last_run_at comes due at both 06:00 UTC (02:00 ET) *and* 06:00 ET.
This reproduces the bug against the real celery crontab, then proves the
_to_tz() conversion fixes it.
"""
from datetime import datetime, timezone as dt_tz
from zoneinfo import ZoneInfo

from celery.schedules import crontab

from app.celery_beat.db_scheduler import _to_tz, _entry_tz

ET = ZoneInfo("America/New_York")


class _FakeRow:
    def __init__(self, timezone):
        self.timezone = timezone


def _daily_6am_et(nowfun):
    return crontab(
        minute=0, hour=6, day_of_month="*", month_of_year="*", day_of_week="*",
        nowfun=nowfun,
    )


def test_entry_tz_defaults_to_eastern():
    assert _entry_tz(_FakeRow(None)) is not None
    assert _entry_tz(_FakeRow("America/New_York")) is not None


def test_to_tz_converts_utc_aware_into_row_tz():
    last_run_et = datetime(2026, 8, 16, 6, 0, tzinfo=ET)
    last_run_utc_aware = last_run_et.astimezone(dt_tz.utc)  # what SQLAlchemy hands back

    converted = _to_tz(last_run_utc_aware, ET)

    assert converted == last_run_et
    assert converted.tzinfo is not None


def test_to_tz_treats_naive_as_utc():
    naive = datetime(2026, 8, 16, 6, 0)
    converted = _to_tz(naive, ET)
    assert converted == naive.replace(tzinfo=dt_tz.utc).astimezone(ET)


def test_buggy_utc_aware_seed_double_fires():
    """Reproduces the exact bug: UTC-aware last_run_at comes due at 02:00 ET."""
    last_run_et = datetime(2026, 8, 16, 6, 0, tzinfo=ET)
    last_run_utc_aware = last_run_et.astimezone(dt_tz.utc)

    now_2am_et = lambda: datetime(2026, 8, 17, 2, 0, tzinfo=ET)
    entry = _daily_6am_et(now_2am_et)

    is_due, _ = entry.is_due(last_run_utc_aware)
    assert is_due is True  # the bug: fires 4 hours early


def test_fixed_seed_is_not_due_at_2am_et_and_is_due_at_6am_et():
    last_run_et = datetime(2026, 8, 16, 6, 0, tzinfo=ET)
    last_run_utc_aware = last_run_et.astimezone(dt_tz.utc)
    fixed_last_run = _to_tz(last_run_utc_aware, ET)

    now_2am_et = lambda: datetime(2026, 8, 17, 2, 0, tzinfo=ET)
    is_due_2am, _ = _daily_6am_et(now_2am_et).is_due(fixed_last_run)
    assert is_due_2am is False

    now_6am_et = lambda: datetime(2026, 8, 17, 6, 0, tzinfo=ET)
    is_due_6am, _ = _daily_6am_et(now_6am_et).is_due(fixed_last_run)
    assert is_due_6am is True
