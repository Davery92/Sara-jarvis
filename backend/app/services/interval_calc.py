"""Pure, timezone-aware interval arithmetic for scheduling — harness/
thinking/personality plan Phase 4.

Why this exists: the harness/Qwen evaluation (2026-09-22) reproduced a
real, repeatable failure — asked "find the earliest 30-minute slot with a
10-minute buffer before and after every event," thinking-OFF answered
`10:50–11:20` for a fixture whose last event ended at 10:50, a ZERO-minute
buffer instead of the required 10. Thinking-on modes got it right on the
same fixture, but "sometimes the model gets the arithmetic right" is not a
reliability story. This module computes it instead: the model's job is to
explain a VERIFIED result, never to do the interval math itself.

No I/O, no DB, no model calls, no app-specific imports beyond stdlib +
`app.core.timezone` for the one shared timezone constant — everything here
is pure and exactly testable. `app.tools.calendar_availability` (a thin,
read-only tool adapter) is the only caller that touches the database or a
tool schema; see its module docstring for that boundary.

A second, more fundamental DST trap surfaced while writing this module's
own test suite (empirically verified, not assumed — see
`tests/test_interval_calc.py::TestBufferedArithmeticAcrossDST` and
`TestComparisonAcrossDST`): Python's `-` and `<`/`>` operators between two
timezone-aware `zoneinfo` datetimes do NOT reliably account for a DST
transition either operand's wall-clock/fold combination straddles.
`(midnight Nov 2) - (midnight Nov 1)` in America/New_York gives exactly
`1 day` via plain `-`, when the real elapsed time across that fall-back
night is 25 hours; two datetimes on opposite sides of the repeated 1-2 AM
hour with different `fold` values can compare `False` for `a < b` via
plain `<` even when `a` is genuinely earlier in absolute time. Every
comparison and subtraction in this module goes through UTC first (`_utc`,
`_later`, `_earlier` below) specifically because of this — not as
defensive-programming boilerplate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo

from app.core.timezone import USER_TIMEZONE

UTC = ZoneInfo("UTC")


class NaiveDatetimeError(ValueError):
    """Raised when a naive (timezone-less) datetime reaches this module.

    Naive arithmetic across a DST boundary is exactly the class of bug this
    module exists to prevent — refuse it loudly rather than silently doing
    wall-clock math that's wrong twice a year.
    """


def _utc(dt: datetime) -> datetime:
    """`dt` converted to UTC — the absolute-instant comparison/arithmetic
    frame every operation in this module uses instead of raw `-`/`<`/`>`
    on aware-but-zoneinfo-backed datetimes. See the module docstring."""
    if dt.tzinfo is None:
        raise NaiveDatetimeError(f"expected a timezone-aware datetime, got {dt!r}")
    return dt.astimezone(UTC)


def _later(a: datetime, b: datetime) -> datetime:
    """Whichever of `a`, `b` is later in absolute time — returns the
    ORIGINAL object (preserving its zone/fold for display), decided by a
    UTC-normalized comparison."""
    return a if _utc(a) >= _utc(b) else b


def _earlier(a: datetime, b: datetime) -> datetime:
    """Whichever of `a`, `b` is earlier in absolute time — returns the
    ORIGINAL object, decided by a UTC-normalized comparison."""
    return a if _utc(a) <= _utc(b) else b


def add_duration(dt: datetime, delta: timedelta) -> datetime:
    """`dt` plus `delta` of REAL elapsed time, in `dt`'s own zone.

    `aware_datetime + timedelta` on a `zoneinfo`-backed datetime adds the
    timedelta to the NAIVE wall-clock components and only re-resolves the
    UTC offset for display, without accounting for any DST transition the
    addition crosses — a 90-minute addition from 1:00 AM EDT (fold=0) on
    the 2026-11-01 fall-back night naively lands on a wall clock of 2:30
    AM, which is actually 150 minutes of real time later, not 90. This does
    the arithmetic in UTC, where a timedelta always means real elapsed
    time, then converts back to the original zone."""
    return (_utc(dt) + delta).astimezone(dt.tzinfo)


@dataclass(frozen=True)
class Interval:
    """A closed-open time span [start, end). Always timezone-aware.

    `start`/`end` are stored exactly as given (so callers get their own
    zone back for display), but every comparison and duration calculation
    below normalizes to UTC first — see the module docstring for why that
    is load-bearing, not defensive style.
    """

    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise NaiveDatetimeError(
                f"Interval requires timezone-aware datetimes, got start={self.start!r} "
                f"end={self.end!r}"
            )
        if _utc(self.end) < _utc(self.start):
            raise ValueError(f"end {self.end.isoformat()} is before start {self.start.isoformat()}")

    @property
    def duration(self) -> timedelta:
        return _utc(self.end) - _utc(self.start)

    def overlaps(self, other: "Interval") -> bool:
        """True for any shared instant. Touching endpoints (this.end ==
        other.start) do NOT count as overlap — [9,10) and [10,11) are
        adjacent, not overlapping; `merge_intervals` treats adjacency as
        mergeable separately, which is a different, deliberate choice from
        "do these two spans share time"."""
        return _utc(self.start) < _utc(other.end) and _utc(other.start) < _utc(self.end)

    def buffered(self, before: timedelta = timedelta(0), after: timedelta = timedelta(0)) -> "Interval":
        """This interval expanded by a buffer on each side, in real
        elapsed time — see `add_duration`."""
        return Interval(add_duration(self.start, -before), add_duration(self.end, after))

    def contains(self, instant: datetime) -> bool:
        return _utc(self.start) <= _utc(instant) < _utc(self.end)


def merge_intervals(intervals: Sequence[Interval]) -> List[Interval]:
    """Union of overlapping-OR-touching intervals, sorted, deduplicated.

    Touching endpoints merge (unlike `Interval.overlaps`) because two busy
    blocks that share a boundary instant leave no usable gap between them —
    treating them as separate would let `free_slots` report a zero-length
    "gap" as real time.
    """
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: _utc(iv.start))
    merged = [ordered[0]]
    for iv in ordered[1:]:
        last = merged[-1]
        if _utc(iv.start) <= _utc(last.end):
            if _utc(iv.end) > _utc(last.end):
                merged[-1] = Interval(last.start, iv.end)
        else:
            merged.append(iv)
    return merged


def free_slots(
    window: Interval,
    busy: Sequence[Interval],
    min_duration: timedelta,
    buffer_before: timedelta = timedelta(0),
    buffer_after: timedelta = timedelta(0),
) -> List[Interval]:
    """Every gap in `window` not covered by a buffered `busy` interval that
    is at least `min_duration` long, earliest first. `busy` may be
    unsorted, overlapping, or empty; buffers are applied to each busy
    interval before merging, so two events 15 minutes apart with a
    10-minute buffer each correctly produce a merged block spanning the
    gap between them, not two separately-buffered blocks with an
    impossible 5-minute sliver counted as free."""
    buffered_busy = [b.buffered(buffer_before, buffer_after) for b in busy]
    merged = merge_intervals(buffered_busy)

    clipped: List[Interval] = []
    for b in merged:
        s, e = _later(b.start, window.start), _earlier(b.end, window.end)
        if _utc(s) < _utc(e):
            clipped.append(Interval(s, e))

    slots: List[Interval] = []
    cursor = window.start
    for b in clipped:
        if _utc(b.start) > _utc(cursor):
            gap = Interval(cursor, b.start)
            if gap.duration >= min_duration:
                slots.append(gap)
        cursor = _later(cursor, b.end)
    if _utc(cursor) < _utc(window.end):
        gap = Interval(cursor, window.end)
        if gap.duration >= min_duration:
            slots.append(gap)
    return slots


def earliest_free_slot(
    window: Interval,
    busy: Sequence[Interval],
    min_duration: timedelta,
    buffer_before: timedelta = timedelta(0),
    buffer_after: timedelta = timedelta(0),
) -> Optional[Interval]:
    """The first slot `free_slots` finds, or None if nothing qualifies.
    Does not truncate a longer slot to `min_duration` — callers that want
    an exact-length booking should slice the front of the returned
    interval themselves; this reports what is actually free."""
    slots = free_slots(window, busy, min_duration, buffer_before, buffer_after)
    return slots[0] if slots else None


def day_window(d: date, tz: ZoneInfo = USER_TIMEZONE) -> Interval:
    """[midnight, next midnight) for `d` in `tz` — the all-day-event span,
    and a convenient default search window. Uses local calendar-day
    boundaries (`date + timedelta(days=1)`, which has no DST concept since
    a bare `date` has no time component), not a fixed 24h duration, so a
    DST-transition day (23 or 25 real hours, per `Interval.duration`)
    still spans exactly that calendar day."""
    start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=tz)
    next_day = d + timedelta(days=1)
    end = datetime(next_day.year, next_day.month, next_day.day, 0, 0, tzinfo=tz)
    return Interval(start, end)


def is_ambiguous_local_time(naive: datetime, tz: ZoneInfo = USER_TIMEZONE) -> bool:
    """True when this naive wall-clock time occurs TWICE in `tz` — the
    fall-back fold (e.g. 1:30 AM on the night clocks go back). Callers
    (a tool adapter, a prompt) should ask which occurrence was meant rather
    than silently picking fold=0 (the default `datetime.replace` behavior)
    when the answer materially changes a buffer/overlap result."""
    if naive.tzinfo is not None:
        raise ValueError("pass a naive datetime — this checks a wall-clock time, not an instant")
    early = naive.replace(tzinfo=tz, fold=0)
    late = naive.replace(tzinfo=tz, fold=1)
    return early.utcoffset() != late.utcoffset()


def is_nonexistent_local_time(naive: datetime, tz: ZoneInfo = USER_TIMEZONE) -> bool:
    """True when this naive wall-clock time never occurred — the
    spring-forward gap (e.g. 2:30 AM on the night clocks jump forward).
    Round-trips through an absolute instant and back; a gap time
    normalizes to a different wall-clock reading than what was asked for."""
    if naive.tzinfo is not None:
        raise ValueError("pass a naive datetime — this checks a wall-clock time, not an instant")
    aware = naive.replace(tzinfo=tz)
    back = _utc(aware).astimezone(tz)
    return back.replace(tzinfo=None) != naive
