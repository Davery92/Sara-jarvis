"""Daily-layer freshness and rollover (chat harness repair Phase 3).

The day layer file only rolled over when a new summary was appended, so a
first read on a new day — before anything had been appended yet — handed the
model yesterday's content under a "## Today (...)" heading. These tests cover
the metadata sidecar and the freshness-checked read path
(`DayLayer.read_fresh`), which `BriefCompiler._read_layer` now uses for the
"day" layer instead of a raw file read.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.daily_brief.day_layer import DayLayer

ET = ZoneInfo("America/New_York")


@pytest.fixture
def day_layer(tmp_path):
    dl = DayLayer()
    dl.briefs_dir = tmp_path
    return dl


def _dt(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def test_read_fresh_empty_when_nothing_written(day_layer):
    result = day_layer.read_fresh("user-1", now=_dt(2026, 9, 16))
    assert result == {"content": "", "is_stale": False, "effective_date": None, "label": "empty"}


def test_read_fresh_current_for_same_day(day_layer):
    ts = _dt(2026, 9, 16, 9, 0)
    day_layer._write_layer("user-1", "## Today (Wednesday, September 16)\n\n**09:00**\nGood morning\n", effective_date=ts)

    result = day_layer.read_fresh("user-1", now=_dt(2026, 9, 16, 10, 30))

    assert result["label"] == "current"
    assert result["is_stale"] is False
    assert "## Today (Wednesday, September 16)" in result["content"]


def test_read_fresh_relabels_stale_content_written_via_metadata(day_layer):
    ts = _dt(2026, 9, 15, 20, 0)
    day_layer._write_layer(
        "user-1",
        "## Today (Tuesday, September 15)\n\n**20:00**\nRingCentral demo went fine\n",
        effective_date=ts,
    )

    result = day_layer.read_fresh("user-1", now=_dt(2026, 9, 16, 8, 0))

    assert result["label"] == "historical"
    assert result["is_stale"] is True
    assert result["effective_date"] == "2026-09-15"
    assert "## Today (" not in result["content"]
    assert "As of 2026-09-15" in result["content"]
    assert "RingCentral demo went fine" in result["content"]  # content preserved, just relabeled


def test_read_fresh_falls_back_to_heading_parse_when_metadata_missing(day_layer):
    # Simulates a file written before the metadata sidecar existed: no
    # day.meta.json, only the markdown file with its heading.
    path = day_layer._get_layer_path("user-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("## Today (Tuesday, September 15)\n\n**20:00**\nOld note\n")

    assert day_layer._get_meta_path("user-1").exists() is False

    result = day_layer.read_fresh("user-1", now=_dt(2026, 9, 16, 8, 0))

    assert result["label"] == "historical"
    assert "## Today (" not in result["content"]
    assert "As of an earlier day" in result["content"]


def test_read_fresh_no_metadata_but_heading_matches_today_is_current(day_layer):
    path = day_layer._get_layer_path("user-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("## Today (Wednesday, September 16)\n\n**09:00**\nFresh note\n")

    result = day_layer.read_fresh("user-1", now=_dt(2026, 9, 16, 10, 0))

    assert result["label"] == "current"
    assert "## Today (Wednesday, September 16)" in result["content"]


def test_read_fresh_minute_before_and_after_midnight(day_layer):
    ts = _dt(2026, 9, 15, 23, 59)
    day_layer._write_layer("user-1", "## Today (Tuesday, September 15)\n\nLate night check-in\n", effective_date=ts)

    just_before = day_layer.read_fresh("user-1", now=_dt(2026, 9, 15, 23, 59))
    assert just_before["label"] == "current"

    just_after = day_layer.read_fresh("user-1", now=_dt(2026, 9, 16, 0, 1))
    assert just_after["label"] == "historical"


def test_read_fresh_uses_eastern_day_even_if_caller_thinks_in_utc(day_layer):
    # 2026-09-16 02:00 UTC is still 2026-09-15 22:00 in America/New_York.
    # A backend process running in UTC must not treat this as a new day.
    utc_ts = datetime(2026, 9, 15, 22, 0, tzinfo=ET)  # the ET-correct instant
    day_layer._write_layer("user-1", "## Today (Tuesday, September 15)\n\nEvening note\n", effective_date=utc_ts)

    same_et_day = datetime(2026, 9, 15, 23, 30, tzinfo=ET)
    result = day_layer.read_fresh("user-1", now=same_et_day)
    assert result["label"] == "current"


@pytest.mark.asyncio
async def test_append_session_summary_archives_on_day_change(day_layer, monkeypatch):
    archived = []

    async def fake_archive(user_id, content):
        archived.append((user_id, content))

    monkeypatch.setattr(day_layer, "_archive_and_reset", fake_archive)

    await day_layer.append_session_summary("user-1", "Talked about the trip", timestamp=_dt(2026, 9, 15, 21, 0))
    await day_layer.append_session_summary("user-1", "Good morning", timestamp=_dt(2026, 9, 16, 8, 0))

    assert len(archived) == 1
    assert "Talked about the trip" in archived[0][1]

    meta = day_layer._read_meta("user-1")
    assert meta["effective_date"] == "2026-09-16"


@pytest.mark.asyncio
async def test_append_session_summary_same_day_does_not_archive(day_layer, monkeypatch):
    archived = []

    async def fake_archive(*a, **kw):
        archived.append(1)

    monkeypatch.setattr(day_layer, "_archive_and_reset", fake_archive)

    await day_layer.append_session_summary("user-1", "First thing", timestamp=_dt(2026, 9, 16, 8, 0))
    await day_layer.append_session_summary("user-1", "Second thing", timestamp=_dt(2026, 9, 16, 9, 0))

    assert archived == []
    content = day_layer.read("user-1")
    assert "First thing" in content
    assert "Second thing" in content
