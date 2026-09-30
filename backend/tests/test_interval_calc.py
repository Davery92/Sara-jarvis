"""Pure interval arithmetic — harness/thinking/personality plan Phase 4.

Exact-value tests reproduce the actual fixture that found the bug this
module exists to prevent (see interval_calc.py's module docstring), plus
boundary/DST/property-style coverage.
"""
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.interval_calc import (
    UTC, Interval, NaiveDatetimeError, add_duration, day_window, earliest_free_slot,
    free_slots, is_ambiguous_local_time, is_nonexistent_local_time, merge_intervals,
)

ET = ZoneInfo("America/New_York")


def t(hour, minute, d=date(2026, 9, 22), tz=ET):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)


class TestIntervalConstruction:
    def test_naive_datetime_is_refused(self):
        with pytest.raises(NaiveDatetimeError):
            Interval(datetime(2026, 9, 22, 9, 0), datetime(2026, 9, 22, 10, 0))

    def test_end_before_start_is_refused(self):
        with pytest.raises(ValueError):
            Interval(t(10, 0), t(9, 0))

    def test_zero_length_interval_is_allowed(self):
        iv = Interval(t(9, 0), t(9, 0))
        assert iv.duration == timedelta(0)


class TestOverlaps:
    def test_true_overlap(self):
        assert Interval(t(9, 0), t(10, 0)).overlaps(Interval(t(9, 30), t(10, 30)))

    def test_touching_is_not_overlap(self):
        assert not Interval(t(9, 0), t(10, 0)).overlaps(Interval(t(10, 0), t(11, 0)))

    def test_disjoint_is_not_overlap(self):
        assert not Interval(t(9, 0), t(10, 0)).overlaps(Interval(t(11, 0), t(12, 0)))

    def test_containment_is_overlap(self):
        assert Interval(t(9, 0), t(12, 0)).overlaps(Interval(t(10, 0), t(10, 30)))

    def test_overlaps_is_symmetric(self):
        a, b = Interval(t(9, 0), t(10, 30)), Interval(t(10, 0), t(11, 0))
        assert a.overlaps(b) == b.overlaps(a)


class TestMergeIntervals:
    def test_empty(self):
        assert merge_intervals([]) == []

    def test_single(self):
        iv = Interval(t(9, 0), t(10, 0))
        assert merge_intervals([iv]) == [iv]

    def test_overlapping_merge(self):
        a, b = Interval(t(9, 0), t(10, 30)), Interval(t(10, 0), t(11, 0))
        assert merge_intervals([a, b]) == [Interval(t(9, 0), t(11, 0))]

    def test_touching_merges(self):
        a, b = Interval(t(9, 0), t(10, 0)), Interval(t(10, 0), t(11, 0))
        assert merge_intervals([a, b]) == [Interval(t(9, 0), t(11, 0))]

    def test_disjoint_stays_separate(self):
        a, b = Interval(t(9, 0), t(10, 0)), Interval(t(11, 0), t(12, 0))
        assert merge_intervals([a, b]) == [a, b]

    def test_unsorted_input_still_correct(self):
        a, b, c = Interval(t(13, 0), t(14, 0)), Interval(t(9, 0), t(10, 0)), Interval(t(9, 30), t(9, 45))
        assert merge_intervals([a, b, c]) == [Interval(t(9, 0), t(10, 0)), Interval(t(13, 0), t(14, 0))]

    def test_fully_contained_interval_is_absorbed(self):
        outer, inner = Interval(t(9, 0), t(12, 0)), Interval(t(10, 0), t(10, 30))
        assert merge_intervals([outer, inner]) == [outer]

    def test_three_way_chain_merges_into_one(self):
        a, b, c = Interval(t(9, 0), t(10, 0)), Interval(t(9, 45), t(11, 0)), Interval(t(10, 50), t(12, 0))
        assert merge_intervals([a, b, c]) == [Interval(t(9, 0), t(12, 0))]


class TestFreeSlotsExactFixture:
    """The actual evaluation fixture (sched_overlap_buffer): 09:15-09:45
    Standup, 10:00-10:50 Design review, 09:00-12:00 window, need 30 minutes
    with a 10-minute buffer before AND after every event. Ground truth:
    11:00-11:30 is the earliest qualifying slot. Thinking-off answered
    10:50-11:20 (zero buffer) on this exact fixture."""

    BUSY = [Interval(t(9, 15), t(9, 45)), Interval(t(10, 0), t(10, 50))]
    WINDOW = Interval(t(9, 0), t(12, 0))

    def test_earliest_slot_honors_the_buffer(self):
        slot = earliest_free_slot(self.WINDOW, self.BUSY, timedelta(minutes=30),
                                   buffer_before=timedelta(minutes=10), buffer_after=timedelta(minutes=10))
        # earliest_free_slot reports the full free span (11:00 to the
        # window end at 12:00), not truncated to the requested 30 minutes —
        # see test_a_60_minute_slot_is_not_truncated_to_the_requested_30.
        assert slot == Interval(t(11, 0), t(12, 0))
        assert slot.start == t(11, 0)  # the load-bearing assertion: buffer honored, not 10:50

    def test_the_zero_buffer_answer_is_provably_wrong(self):
        """10:50-11:20 is what thinking-off said. It starts exactly when
        the Design review ends — a zero-minute buffer, not ten."""
        wrong = Interval(t(10, 50), t(11, 20))
        buffered_design_review = Interval(t(10, 0), t(10, 50)).buffered(timedelta(minutes=10), timedelta(minutes=10))
        assert wrong.overlaps(buffered_design_review)

    def test_without_a_buffer_the_gap_right_after_design_review_would_qualify(self):
        slot = earliest_free_slot(self.WINDOW, self.BUSY, timedelta(minutes=30))
        assert slot.start == t(10, 50)

    def test_all_qualifying_slots_in_order(self):
        slots = free_slots(self.WINDOW, self.BUSY, timedelta(minutes=30),
                            buffer_before=timedelta(minutes=10), buffer_after=timedelta(minutes=10))
        assert slots == [Interval(t(11, 0), t(12, 0))]


class TestFreeSlotsBoundaries:
    def test_no_busy_intervals_whole_window_is_free(self):
        window = Interval(t(9, 0), t(12, 0))
        assert free_slots(window, [], timedelta(minutes=30)) == [window]

    def test_busy_interval_entirely_outside_window_is_ignored(self):
        window = Interval(t(9, 0), t(12, 0))
        outside = Interval(t(13, 0), t(14, 0))
        assert free_slots(window, [outside], timedelta(minutes=30)) == [window]

    def test_busy_interval_partially_outside_window_is_clipped(self):
        window = Interval(t(9, 0), t(12, 0))
        spanning = Interval(t(8, 0), t(10, 0))
        assert free_slots(window, [spanning], timedelta(minutes=30)) == [Interval(t(10, 0), t(12, 0))]

    def test_busy_interval_covering_the_whole_window_leaves_nothing(self):
        window = Interval(t(9, 0), t(12, 0))
        assert free_slots(window, [Interval(t(8, 0), t(13, 0))], timedelta(minutes=30)) == []

    def test_a_gap_shorter_than_min_duration_is_excluded(self):
        window = Interval(t(9, 0), t(12, 0))
        busy = [Interval(t(9, 0), t(9, 50)), Interval(t(10, 0), t(12, 0))]
        # the 9:50-10:00 gap is 10 minutes; asking for 30 must not return it
        assert free_slots(window, busy, timedelta(minutes=30)) == []

    def test_a_gap_exactly_min_duration_is_included(self):
        window = Interval(t(9, 0), t(12, 0))
        busy = [Interval(t(9, 0), t(9, 30)), Interval(t(10, 0), t(12, 0))]
        assert free_slots(window, busy, timedelta(minutes=30)) == [Interval(t(9, 30), t(10, 0))]

    def test_buffer_merges_two_events_that_would_otherwise_leave_an_unusable_sliver(self):
        """Two events 15 minutes apart; a 10-minute buffer on each side
        leaves a real gap of -5 minutes, i.e. none — the merge must absorb
        it rather than reporting an impossible negative-width slot as free."""
        window = Interval(t(9, 0), t(12, 0))
        busy = [Interval(t(9, 0), t(9, 30)), Interval(t(9, 45), t(10, 30))]
        slots = free_slots(window, busy, timedelta(minutes=5),
                            buffer_before=timedelta(minutes=10), buffer_after=timedelta(minutes=10))
        assert slots == [Interval(t(10, 40), t(12, 0))]

    def test_earliest_free_slot_returns_none_when_nothing_qualifies(self):
        window = Interval(t(9, 0), t(9, 20))
        assert earliest_free_slot(window, [], timedelta(minutes=30)) is None

    def test_a_60_minute_slot_is_not_truncated_to_the_requested_30(self):
        window = Interval(t(9, 0), t(12, 0))
        slot = earliest_free_slot(window, [], timedelta(minutes=30))
        assert slot.duration == timedelta(hours=3)


class TestDayWindow:
    def test_ordinary_day_is_24_hours(self):
        # 2026-09-22 has no DST transition in America/New_York.
        w = day_window(date(2026, 9, 22))
        assert w.duration == timedelta(hours=24)

    def test_fall_back_day_is_25_hours(self):
        # DST ends 2026-11-01 in the US (clocks fall back at 2:00 AM).
        w = day_window(date(2026, 11, 1))
        assert w.duration == timedelta(hours=25)

    def test_spring_forward_day_is_23_hours(self):
        # DST begins 2026-03-08 in the US (clocks spring forward at 2:00 AM).
        w = day_window(date(2026, 3, 8))
        assert w.duration == timedelta(hours=23)


class TestDSTAmbiguousAndNonexistentLocalTimes:
    def test_fall_back_130am_is_ambiguous(self):
        assert is_ambiguous_local_time(datetime(2026, 11, 1, 1, 30)) is True

    def test_an_ordinary_time_is_not_ambiguous(self):
        assert is_ambiguous_local_time(datetime(2026, 9, 22, 9, 0)) is False

    def test_spring_forward_230am_does_not_exist(self):
        assert is_nonexistent_local_time(datetime(2026, 3, 8, 2, 30)) is True

    def test_an_ordinary_time_exists(self):
        assert is_nonexistent_local_time(datetime(2026, 9, 22, 9, 0)) is False

    def test_fall_back_130_is_not_flagged_as_nonexistent(self):
        """It's ambiguous (happens twice), not missing — a different
        failure mode with a different correct response (ask which
        occurrence, not "that time doesn't exist")."""
        assert is_nonexistent_local_time(datetime(2026, 11, 1, 1, 30)) is False

    def test_the_reproduced_eval_case_is_genuinely_ambiguous(self):
        """The evaluation's sched_dst_boundary fixture asked about 01:30
        New York time on the fall-back morning and was marked 'not a
        reliable oracle' because the fixture's own wording was self-
        contradictory. This is the fixture's premise stated correctly and
        checked deterministically: 01:30 on 2026-11-01 really is ambiguous,
        which is exactly why a model answering 'yes' or 'no' to an offset
        question about it without asking which occurrence is guessing."""
        assert is_ambiguous_local_time(datetime(2026, 11, 1, 1, 30)) is True


class TestBufferedArithmeticAcrossDST:
    def test_naive_wall_clock_addition_would_have_been_wrong(self):
        """Document the actual bug this module's `add_duration` fixes:
        plain `aware_datetime + timedelta` on a zoneinfo datetime does NOT
        account for a DST transition it crosses. This is Python's real,
        documented behavior — verified here, not assumed — so the fix
        below is checked against a concrete wrong answer, not a strawman."""
        start = datetime(2026, 11, 1, 1, 0, tzinfo=ET, fold=0)
        naively_added = start + timedelta(minutes=90)  # the trap
        assert naively_added.hour == 2 and naively_added.minute == 30
        real_elapsed = naively_added.astimezone(UTC) - start.astimezone(UTC)
        assert real_elapsed == timedelta(minutes=150)  # NOT 90 — the bug

    def test_add_duration_gives_the_correct_90_real_minutes(self):
        """1:00 AM EDT (fold=0) plus 90 REAL minutes, spanning the
        fall-back transition, lands at 1:30 AM EST (fold=1) — the second
        occurrence of the 1:00-2:00 AM hour, 60 minutes to loop back to
        1:00 AM fold=1 plus 30 more minutes. Not 2:30, which is what naive
        wall-clock addition (previous test) produces."""
        start = datetime(2026, 11, 1, 1, 0, tzinfo=ET, fold=0)
        end = add_duration(start, timedelta(minutes=90))
        assert end.hour == 1 and end.minute == 30
        assert end.fold == 1
        assert end.utcoffset() == timedelta(hours=-5)  # EST, the post-transition offset
        assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(minutes=90)

    def test_interval_buffered_uses_real_elapsed_time_not_wall_clock(self):
        """The property that actually matters for scheduling: a 90-minute
        buffer added to an interval ending at 1:00 AM EDT (fold=0) must
        produce a NEW interval whose real duration grew by exactly 90
        minutes, across the fall-back transition."""
        iv = Interval(t(0, 0, d=date(2026, 11, 1)), datetime(2026, 11, 1, 1, 0, tzinfo=ET, fold=0))
        buffered = iv.buffered(after=timedelta(minutes=90))
        real_growth = buffered.end.astimezone(UTC) - iv.end.astimezone(UTC)
        assert real_growth == timedelta(minutes=90)

    def test_an_ordinary_days_buffer_is_unaffected(self):
        """No transition crossed — add_duration and naive addition agree."""
        start = t(9, 0)
        assert add_duration(start, timedelta(minutes=10)) == start + timedelta(minutes=10)


class TestComparisonAcrossDST:
    """A second, more fundamental DST trap than the addition one above:
    plain `<`/`>` between two aware zoneinfo datetimes can also be wrong —
    not just `-`. Two datetimes both inside the repeated 1-2 AM hour on
    fall-back night, with different `fold`, compare incorrectly via plain
    `<` even though one really is earlier. Verified here against the raw
    Python operator, then checked that Interval.overlaps (which goes
    through UTC) gets it right anyway."""

    def test_the_raw_python_bug_this_module_works_around(self):
        """Document the actual wrong behavior, not a hypothetical: `a` at
        1:30 EDT (fold=0) is REALLY earlier than `b` at 1:15 EST (fold=1)
        — 05:30 UTC vs 06:15 UTC — but plain `<` says otherwise."""
        a = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=0)
        b = datetime(2026, 11, 1, 1, 15, tzinfo=ET, fold=1)
        assert a.astimezone(UTC) < b.astimezone(UTC)  # a really is earlier
        assert not (a < b)  # but Python's raw operator disagrees

    def test_interval_overlaps_gets_the_straddling_case_right(self):
        """A 20-minute call starting at the earlier real instant (1:30 EDT
        fold=0) must be reported as overlapping a call starting at the
        later real instant (1:15 EST fold=1) once real time is accounted
        for — 1:30-1:50 EDT (=05:30-05:50 UTC) does not reach 1:15 EST
        (=06:15 UTC), so this specific pair should NOT overlap; the point
        is that Interval computes that correctly via UTC, not that it
        happens to overlap."""
        a = Interval(datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=0),
                     datetime(2026, 11, 1, 1, 50, tzinfo=ET, fold=0))
        b = Interval(datetime(2026, 11, 1, 1, 15, tzinfo=ET, fold=1),
                     datetime(2026, 11, 1, 1, 45, tzinfo=ET, fold=1))
        # a: 05:30-05:50 UTC, b: 06:15-06:45 UTC — genuinely disjoint.
        assert not a.overlaps(b)
        assert not b.overlaps(a)

    def test_interval_overlaps_correctly_finds_a_real_straddling_overlap(self):
        """Now construct a pair that DOES really overlap once fold is
        accounted for, and confirm Interval agrees (the raw `<` operator,
        per the previous test, cannot be trusted to get this right).
        `a` starts at 1:30 EDT (fold=0, = 05:30 UTC) and runs 80 real
        minutes via `add_duration`, reaching 06:50 UTC — past `b`'s start
        at 1:15 EST (fold=1, = 06:15 UTC)."""
        a_start = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=0)
        a = Interval(a_start, add_duration(a_start, timedelta(hours=1, minutes=20)))
        b = Interval(datetime(2026, 11, 1, 1, 15, tzinfo=ET, fold=1),
                     datetime(2026, 11, 1, 1, 45, tzinfo=ET, fold=1))
        assert a.overlaps(b)
        assert b.overlaps(a)

    def test_duration_across_the_full_fall_back_night_is_25_hours(self):
        w = day_window(date(2026, 11, 1))
        assert w.duration == timedelta(hours=25)


class TestMergeInvariant:
    """Property-style check (no hypothesis dependency available): across
    many random interval sets, the merged result must (a) cover exactly
    the same total duration as a naive O(n^2) reference union, and (b)
    contain no two intervals that touch or overlap each other."""

    def _naive_union_duration(self, intervals, resolution=timedelta(minutes=1)):
        if not intervals:
            return timedelta(0)
        start = min(iv.start for iv in intervals)
        end = max(iv.end for iv in intervals)
        covered = 0
        cursor = start
        while cursor < end:
            nxt = cursor + resolution
            mid = cursor + resolution / 2
            if any(iv.contains(mid) for iv in intervals):
                covered += 1
            cursor = nxt
        return resolution * covered

    @pytest.mark.parametrize("seed", range(25))
    def test_random_interval_sets(self, seed):
        rnd = random.Random(seed)
        base = t(0, 0)
        intervals = []
        for _ in range(rnd.randint(0, 8)):
            start_min = rnd.randint(0, 24 * 60 - 5)
            length = rnd.randint(1, 120)
            intervals.append(Interval(base + timedelta(minutes=start_min),
                                       base + timedelta(minutes=start_min + length)))
        merged = merge_intervals(intervals)

        # No two merged intervals touch or overlap.
        for i in range(len(merged) - 1):
            assert merged[i].end < merged[i + 1].start

        # Coverage matches a naive reference at 1-minute resolution.
        naive = self._naive_union_duration(intervals, resolution=timedelta(minutes=1))
        merged_total = sum((iv.duration for iv in merged), timedelta())
        assert merged_total == naive
