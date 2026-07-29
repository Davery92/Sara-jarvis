"""
Tests for voice_linter — the deterministic style-contract auditor.

Focused on the machinery-narration leak class found live during Arc 1.3
shadow verification: a compose draft that talks about its own send/no-send
decision ("I'm sending silence", "keeping it quiet") instead of just staying
silent. The voice contract bans narrating the machinery either way.
"""
from app.services.voice_linter import lint_rows


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
