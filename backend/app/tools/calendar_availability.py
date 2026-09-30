"""Read-only calendar availability tool — harness/thinking/personality plan
Phase 4.

The thin adapter `interval_calc.py`'s own docstring promises: fetches real
events for a window, converts them to `Interval`s (including bounded
recurrence expansion via `dateutil.rrule` — the app's own `build_rrule`
already produces standard RRULE strings; this is not a new recurrence
dialect), and hands the VERIFIED result to `interval_calc.earliest_free_
slot`/`free_slots`. The model explains this result; it never computes the
interval math itself. Read-only: never in `app.tools.mutating.WRITE_TOOLS`,
touches the database with a plain SELECT only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import or_

from app.tools.base import BaseTool, ToolResult
from app.tools.calendar import CalendarEvent, USER_TIMEZONE
from app.db.session import get_db
from app.services.interval_calc import (
    Interval, add_duration, day_window, free_slots,
    is_ambiguous_local_time, is_nonexistent_local_time,
)

# Recurrence expansion is bounded to this many occurrences per event — a
# malformed COUNT-less, UNTIL-less RRULE (frequency only) is technically
# infinite; dateutil's rrule iterator would happily run forever without a
# cap when combined with `between()`'s own window bound, but capping here
# keeps a single bad row from doing unbounded work regardless.
_MAX_RECURRENCE_OCCURRENCES = 366


def _expand_event_to_intervals(event: CalendarEvent, window: Interval) -> List[Interval]:
    """One event row -> the Intervals it contributes inside `window`.

    A non-recurring event contributes at most one (clipped to the window).
    A recurring event (has `rrule`) is expanded via `dateutil.rrule` using
    the event's own start as DTSTART and its duration preserved per
    occurrence; a malformed RRULE string is skipped for expansion (falls
    back to just the parent row's own single occurrence) rather than
    failing the whole availability query — a bad recurrence row must not
    make Sara blind to every OTHER event in the window.
    """
    start_local = event.start_time.replace(tzinfo=USER_TIMEZONE)
    end_local = event.end_time.replace(tzinfo=USER_TIMEZONE)
    base = Interval(start_local, end_local)
    duration = base.duration  # DST-correct (Interval.duration goes through UTC)

    if not event.rrule:
        return [base] if base.overlaps(window) else []

    try:
        from dateutil.rrule import rrulestr
        rule = rrulestr(event.rrule, dtstart=start_local.replace(tzinfo=None))
        occurrences = rule.between(
            window.start.replace(tzinfo=None) - duration,  # an occurrence starting just
            window.end.replace(tzinfo=None),                # before the window can still overlap it
            inc=True,
        )[:_MAX_RECURRENCE_OCCURRENCES]
    except Exception:
        return [base] if base.overlaps(window) else []

    intervals = []
    for occ_naive in occurrences:
        occ_start = occ_naive.replace(tzinfo=USER_TIMEZONE)
        occ = Interval(occ_start, occ_start + duration)  # nominal duration; see note below
        if occ.overlaps(window):
            intervals.append(occ)
    return intervals
    # Note: `occ_start + duration` uses plain `+`, not `add_duration` — an
    # event's NOMINAL wall-clock length (e.g. "this meeting is always
    # 9:00-9:30 local time") is the correct interpretation for a recurring
    # series, not a fixed real-time offset that would drift the meeting's
    # displayed time across a DST boundary. This is a deliberate exception
    # to "always use add_duration," not an oversight.


class CalendarAvailabilityTool(BaseTool):
    """Deterministic earliest-free-slot search — read-only."""

    @property
    def name(self) -> str:
        return "calendar_find_availability"

    @property
    def description(self) -> str:
        return (
            "Find the earliest free time slot on the calendar within a date/time window, "
            "honoring buffers before and after existing events. Computed deterministically "
            "from real events — not estimated. Read-only; does not create or change anything."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date to search, YYYY-MM-DD. Defaults to today."},
                "window_start_time": {"type": "string", "description": "Earliest local time to consider, HH:MM (24h). Defaults to 00:00."},
                "window_end_time": {"type": "string", "description": "Latest local time to consider, HH:MM (24h). Defaults to 23:59."},
                "duration_minutes": {"type": "integer", "description": "Minimum free duration needed, in minutes.", "default": 30},
                "buffer_before_minutes": {"type": "integer", "description": "Required gap before each existing event.", "default": 0},
                "buffer_after_minutes": {"type": "integer", "description": "Required gap after each existing event.", "default": 0},
                "all_slots": {"type": "boolean", "description": "Return every qualifying slot, not just the earliest.", "default": False},
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            target_date = (
                datetime.strptime(kwargs["date"], "%Y-%m-%d").date()
                if kwargs.get("date") else datetime.now(USER_TIMEZONE).date()
            )
        except ValueError:
            return ToolResult(success=False, message="Invalid date format. Use YYYY-MM-DD.")

        day = day_window(target_date)
        window = day
        for key, attr in (("window_start_time", "start"), ("window_end_time", "end")):
            raw = kwargs.get(key)
            if not raw:
                continue
            try:
                hh, mm = (int(p) for p in raw.split(":"))
            except (ValueError, AttributeError):
                return ToolResult(success=False, message=f"Invalid {key} — use HH:MM (24h).")
            naive = datetime(target_date.year, target_date.month, target_date.day, hh, mm)
            if is_nonexistent_local_time(naive, USER_TIMEZONE):
                return ToolResult(success=False, message=(
                    f"{raw} on {target_date.isoformat()} does not exist — clocks skip that time "
                    "on this date (spring-forward transition). Ask which side of the gap was meant."
                ))
            if is_ambiguous_local_time(naive, USER_TIMEZONE):
                return ToolResult(success=False, message=(
                    f"{raw} on {target_date.isoformat()} is ambiguous — that time occurs twice "
                    "(fall-back transition). Ask which occurrence was meant before proceeding."
                ))
            replacement = naive.replace(tzinfo=USER_TIMEZONE)
            window = Interval(replacement, window.end) if attr == "start" else Interval(window.start, replacement)

        duration = timedelta(minutes=kwargs.get("duration_minutes", 30))
        buffer_before = timedelta(minutes=kwargs.get("buffer_before_minutes", 0))
        buffer_after = timedelta(minutes=kwargs.get("buffer_after_minutes", 0))

        db_gen = get_db()
        db = next(db_gen)
        try:
            # Widen the DB query beyond the search window by the longer
            # buffer (plus a day for recurrence expansion headroom), so an
            # event whose buffered tail extends into the window — or a
            # recurring series whose stored anchor sits outside it — is
            # not missed. Naive-local bounds, matching the DB's storage
            # convention (see CalendarListTool).
            query_pad = max(buffer_before, buffer_after) + timedelta(days=1)
            query_start_naive = add_duration(window.start, -query_pad).replace(tzinfo=None)
            query_end_naive = add_duration(window.end, query_pad).replace(tzinfo=None)
            # A recurring event's own stored row is its FIRST occurrence,
            # which can be arbitrarily long before the query window (a
            # weekly standup anchored months ago still recurs today) — so
            # the ordinary "does this row's own start/end overlap the
            # window" filter would wrongly exclude it. Any row with an
            # rrule only needs to have STARTED by the window's end;
            # `_expand_event_to_intervals` bounds the actual occurrences
            # to the window afterward.
            rows = db.query(CalendarEvent).filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.start_time <= query_end_naive,
                or_(
                    CalendarEvent.end_time >= query_start_naive,
                    CalendarEvent.rrule.isnot(None),
                ),
            ).all()
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

        busy: List[Interval] = []
        for event in rows:
            busy.extend(_expand_event_to_intervals(event, window))

        slots = free_slots(window, busy, duration, buffer_before, buffer_after)
        if not slots:
            return ToolResult(
                success=True,
                data={"slots": [], "window": {"start": window.start.isoformat(), "end": window.end.isoformat()}},
                message=(
                    f"No slot of at least {kwargs.get('duration_minutes', 30)} minutes found "
                    f"between {window.start.strftime('%I:%M %p')} and {window.end.strftime('%I:%M %p')} "
                    f"on {target_date.isoformat()}, honoring the requested buffers."
                ),
            )

        reported = slots if kwargs.get("all_slots") else slots[:1]
        slot_data = [{"start": s.start.isoformat(), "end": s.end.isoformat(),
                       "duration_minutes": int(s.duration.total_seconds() // 60)} for s in reported]
        return ToolResult(
            success=True,
            data={"slots": slot_data, "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
                  "busy_count": len(busy)},
            message=(
                f"Earliest qualifying slot: {slot_data[0]['start']} to {slot_data[0]['end']}."
                if not kwargs.get("all_slots") else
                f"{len(reported)} qualifying slot(s) found."
            ),
        )
