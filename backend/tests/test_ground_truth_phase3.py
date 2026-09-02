"""Ground-truth Phase 3: one clock.

Sara ran three time conventions at once. `world_thread.due_at` was UTC and went
straight into prompts, `calendar_event.start_time` is naive ET, `notification_ack`
formatted UTC with `%a %H:%M`, and the journal formatted UTC with `%I:%M %p`. So a
thread due 1:00 PM ET was announced as "your 5:00 AM EDT call", and a journal line
written at 5:38 AM read "09:38 AM David is asleep".

Every moment now reaches a prompt or a message through `render_when` and nothing
else — and a naive datetime with no stated convention raises rather than guessing.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
from datetime import date, datetime, timezone

import pytest

from app.core.timezone import render_when

# 2026-09-01 13:50 ET, the moment the fixture in the plan is anchored to.
NOW = datetime(2026, 9, 1, 17, 50, tzinfo=timezone.utc)


class TestRenderWhen:
    def test_the_three_conventions_agree(self):
        """The plan's acceptance fixture: a thread due 17:00Z, a calendar row at
        naive 13:00 ET, and a push sent 10:00Z."""
        assert render_when(datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc), now=NOW) \
            .startswith("Tue Sep 1, 1:00 PM ET")
        assert render_when(datetime(2026, 9, 1, 13, 0), now=NOW, source_convention="et") \
            .startswith("Tue Sep 1, 1:00 PM ET")
        assert render_when(datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc), now=NOW) \
            .startswith("Tue Sep 1, 6:00 AM ET")

    def test_it_says_how_far_away(self):
        assert "(in 3h 10m)" in render_when(
            datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc), now=NOW)
        assert "(3h 50m ago)" in render_when(
            datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc), now=NOW)
        assert "(now)" in render_when(
            datetime(2026, 9, 1, 17, 50, 30, tzinfo=timezone.utc), now=NOW)

    def test_an_all_day_date_never_gets_a_midnight_time(self):
        rendered = render_when(date(2026, 9, 3), now=NOW)
        assert rendered == "Thu Sep 3 (all day)"
        assert "12:00 AM" not in rendered

    def test_a_naive_datetime_without_a_convention_raises(self):
        """The guess is the bug. Refusing to make one is the fix."""
        with pytest.raises(ValueError, match="source_convention"):
            render_when(datetime(2026, 9, 1, 13, 0), now=NOW)

    def test_nothing_renders_as_nothing(self):
        assert render_when(None) == ""

    def test_a_year_boundary_shows_the_year(self):
        assert "2027" in render_when(
            datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc), now=NOW)


class TestNoRawTimestampsInPromptBuilders:
    """Invariant 4 is enforced by a lint, not by vigilance."""

    def test_the_lint_is_clean(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        script = repo / "scripts" / "check_naive_datetime.py"
        if not script.exists():  # pragma: no cover - script lives outside the image
            pytest.skip("check_naive_datetime.py is not mounted in this container")
        result = subprocess.run(
            [sys.executable, str(script), str(repo / "backend" / "app")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout

    def test_the_lint_actually_catches_a_raw_timestamp(self, tmp_path):
        """A lint nobody has seen fail is not a lint."""
        repo = pathlib.Path(__file__).resolve().parents[2]
        script = repo / "scripts" / "check_naive_datetime.py"
        if not script.exists():  # pragma: no cover
            pytest.skip("check_naive_datetime.py is not mounted in this container")

        bad = tmp_path / "services" / "world_state"
        bad.mkdir(parents=True)
        (bad / "leaky.py").write_text(
            'def build():\n    return f"due {due_at.isoformat()}"\n'
        )
        result = subprocess.run(
            [sys.executable, str(script), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "render_when" in result.stdout


class TestHalfDetectedMeetings:
    def test_the_linker_refuses_a_subject_with_no_distinctive_words(self):
        """"Meeting invite" names nothing; matching on it would attach the mail
        to whatever meeting happened to be nearby."""
        import asyncio
        from types import SimpleNamespace
        from app.tasks.email_sync import _link_meeting_to_calendar

        email = SimpleNamespace(
            id="m1", subject="Meeting invite", received_at=None, calendar_event_id=None,
        )
        assert asyncio.run(_link_meeting_to_calendar(None, "u1", email)) is False
        assert email.calendar_event_id is None
