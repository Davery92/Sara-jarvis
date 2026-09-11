"""World brief rendering after the harness rebuild Phase 6 diet.

The 2026-09-11 live context carried, inside one prompt:
  - "David: engaged (interruptibility 1.00). You feel: proud (0.42)" at the top
    and "David: unknown ... You feel: attentive (0.30)" 160 lines later, from a
    cached copy of the same header;
  - every HAPPENED and COMMS line prefixed with a 40-to-200-character key
    nothing reads (a Graph message id is not something email_search takes);
  - Everett's dentist listed twice, once as a thread slug and once as
    `[cal:<uuid>]`;
  - eight OPEN LOOPS, two of which were Sara's own turns ("Waiting for Sara to
    check capability to download attachments") and one four days stale.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import world_brief as wb


NOW = datetime(2026, 9, 11, 9, 31, tzinfo=timezone.utc)


class TestInlineOwner:
    def test_a_persons_event_reads_inline(self):
        assert wb._inline_owner("[Everett's] Meet the Instruments — not David's") == (
            "Meet the Instruments (Everett's)"
        )

    def test_the_family_reads_as_the_family(self):
        assert wb._inline_owner(
            "[the family's] Birthday Celebration with The Clan — not David's"
        ) == "Birthday Celebration with The Clan (the family)"

    def test_unclear_ownership_survives(self):
        assert wb._inline_owner("[owner unclear] Dinner at The Red Hen") == (
            "Dinner at The Red Hen (owner unclear)"
        )

    def test_davids_own_event_is_untouched(self):
        assert wb._inline_owner("Pay Day (all day)") == "Pay Day (all day)"

    def test_the_marker_is_never_silently_dropped(self):
        """This is the marker that stops Everett's dentist being narrated as
        David's morning — it may get shorter, never absent."""
        out = wb._inline_owner("[Everett's] Everett Dentist — not David's")
        assert "Everett's" in out


class TestSarasOwnLoops:
    @pytest.mark.parametrize("text", [
        "Waiting for Sara to check capability to download attachments",
        "Sara to look into the vector search thing",
        "Sara commitment: watching the Jetson deploy",
    ])
    def test_recognised(self, text):
        assert wb._is_saras_own_loop(text) is True

    @pytest.mark.parametrize("text", [
        "Jim Venezia proposed moving company funds to a Morgan Stanley account",
        "Reviewing Jim's emails about new tools",
        "Waiting for Matt Albano to forward the LLC transfer documents",
    ])
    def test_real_loops_survive(self, text):
        assert wb._is_saras_own_loop(text) is False


class TestLoopStaleness:
    def test_a_week_old_loop_is_stale(self):
        old = (NOW - timedelta(days=9)).isoformat()
        assert wb._loop_is_stale(old, NOW) is True

    def test_a_recent_loop_is_not(self):
        recent = (NOW - timedelta(days=2)).isoformat()
        assert wb._loop_is_stale(recent, NOW) is False

    def test_an_undated_loop_is_kept(self):
        # No date is not evidence of staleness; dropping these would silently
        # lose loops whose source never stamped them.
        assert wb._loop_is_stale(None, NOW) is False


class TestHrvProvenance:
    """One prompt cannot hold two different HRV answers.

    On 2026-09-11 the health slice said `hrv=unavailable (nothing recorded in
    the last 36h)` and the training brief, 40 lines later, said "Recovery: high
    HRV (HRV 72)". The 72 came from a daily_recovery_log row, not a watch
    sample. Sara opened the morning with "Recovery looks solid — HRV 72".
    health_metric is the only authority for a number about David's body.
    """

    def test_get_morning_recovery_reports_where_the_number_came_from(self):
        import inspect
        from app.services import progressive_overload as po

        src = inspect.getsource(po.get_morning_recovery)
        assert '"hrv_source"' in src
        assert '"daily_recovery_log"' in src
        assert '"health_metric"' in src

    def test_a_recovery_log_hrv_is_labelled_in_the_brief(self):
        import inspect

        src = inspect.getsource(wb._body_training_live)
        assert 'hrv_source' in src
        assert "not a watch reading today" in src

    def test_provenance_does_not_make_an_empty_recovery_render(self):
        import inspect

        src = inspect.getsource(wb._body_training_live)
        # A dict of all-None metrics plus a provenance string must not satisfy
        # the "is there anything to say" check.
        assert 'if k != "hrv_source"' in src
