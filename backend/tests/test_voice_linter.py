"""
Tests for voice_linter — the deterministic style-contract auditor.

Focused on the machinery-narration leak class found live during Arc 1.3
shadow verification: a compose draft that talks about its own send/no-send
decision ("I'm sending silence", "keeping it quiet") instead of just staying
silent. The voice contract bans narrating the machinery either way.
"""
from app.services.voice_linter import lint_rows, lint_hedging, infer_domain


def _row(message, source="test", category="checkin", title=""):
    return {"title": title, "message": message, "category": category, "source": source}


class TestMachineryNarrationLeak:
    def test_sending_silence_flagged(self):
        report = lint_rows([_row("The rain candidate was stale, so I'm sending silence.")])
        assert report["violations"] == 1
        assert "monologue" in report["examples"][0]["reasons"]

    def test_keeping_it_quiet_flagged(self):
        report = lint_rows([_row("Nothing new here — keeping it quiet for now.")])
        assert report["violations"] == 1

    def test_nothing_to_report_flagged(self):
        report = lint_rows([_row("Nothing to report — the pipeline is clear.")])
        assert report["violations"] == 1

    def test_not_sending_this_flagged(self):
        report = lint_rows([_row("Not sending this. This is noise, not a payload.")])
        assert report["violations"] == 1

    def test_real_payload_not_flagged(self):
        report = lint_rows([_row("Rich replied to the IRMI thread — worth a look before your 2:30.")])
        assert report["violations"] == 0
        assert report["register_score"] == 1.0


class TestExistingRulesUnaffected:
    def test_shout_title_still_flagged(self):
        report = lint_rows([_row("normal message", title="URGENT ACTION NEEDED")])
        assert report["violations"] == 1
        assert "shout" in report["examples"][0]["reasons"]

    def test_robotic_title_still_flagged(self):
        report = lint_rows([_row("something happened", title="Alert: something happened")])
        assert report["violations"] == 1
        assert "robotic" in report["examples"][0]["reasons"]


class TestInferDomain:
    def test_calendar_keywords(self):
        assert infer_domain({"kind": "prep", "summary": "Meeting with John at 2:30"}) == "calendar"

    def test_health_keywords(self):
        assert infer_domain({"kind": "alert", "summary": "HRV dropped to 45 after the workout"}) == "health"

    def test_home_keywords(self):
        assert infer_domain({"kind": "inform", "summary": "Kitchen light turned on"}) == "home"

    def test_unclassifiable_falls_back_to_routine(self):
        assert infer_domain({"kind": "inform", "summary": "xyzzy plugh"}) == "routine"


class TestLintHedging:
    """Arc 4.1: 'the composer/linter must hedge any claim whose domain
    confidence is below threshold' — the mechanical fix for the morning
    brief announcing a '9:30 standing meeting today' the calendar actually
    had Wednesday 2:30 PM. This is the acceptance test named in the plan:
    a synthetic low-confidence claim must be caught."""

    def test_high_confidence_domain_never_requires_hedging(self):
        result = lint_hedging(
            "You have a 9:30 standing meeting today.", "calendar",
            {"calendar": 0.95}, min_confidence=0.7,
        )
        assert result["required"] is False
        assert result["violation"] is False

    def test_unmeasured_domain_is_not_a_violation(self):
        """No calibration data yet != proven unreliable — don't punish
        silence in the data with a forced hedge."""
        result = lint_hedging(
            "You have a 9:30 standing meeting today.", "calendar",
            {}, min_confidence=0.7,
        )
        assert result["required"] is False
        assert result["violation"] is False

    def test_low_confidence_unhedged_claim_is_a_violation(self):
        """The exact reproduced bug: a flat factual claim in a domain
        calibration has proven unreliable, with zero hedge language."""
        result = lint_hedging(
            "You have a 9:30 standing meeting today.", "calendar",
            {"calendar": 0.43}, min_confidence=0.7,
        )
        assert result["required"] is True
        assert result["hedged"] is False
        assert result["violation"] is True

    def test_low_confidence_hedged_claim_passes(self):
        result = lint_hedging(
            "I think you might have a 9:30 meeting today, but double check.",
            "calendar", {"calendar": 0.43}, min_confidence=0.7,
        )
        assert result["required"] is True
        assert result["hedged"] is True
        assert result["violation"] is False

    def test_various_hedge_phrasings_all_recognized(self):
        for phrase in (
            "It looks like you have a meeting today.",
            "As far as I can tell, that's still on.",
            "Probably still happening today.",
            "Last I checked, it was at 2:30.",
        ):
            result = lint_hedging(phrase, "calendar", {"calendar": 0.4}, min_confidence=0.7)
            assert result["violation"] is False, f"expected {phrase!r} to count as hedged"
