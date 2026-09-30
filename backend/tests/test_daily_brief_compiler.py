"""
gotcha_chat_amnesia_brief_clip_2026_09_06, Phase 1 §3: the compiled brief
string is still read by non-chat consumers (notifications, brief_service's
own fallback), so a giant stable layer must not be able to push the
volatile context/day/moment layers out of the compiled string the way it
pushed them out of chat's clip.
"""
from app.services.daily_brief.compiler import BriefCompiler


def test_assemble_puts_volatile_layers_before_stable():
    compiler = BriefCompiler()
    layers = {
        "stable": "x" * 6000,
        "context": "David is currently in Salem (until Monday, Sept 7).",
        "day": "Visited Count Orlok's Nightmare Gallery today.",
        "moment": "Good morning!",
    }
    compiled = compiler._assemble(layers)
    assert compiled.index("in Salem") < compiled.index("x" * 100)


def test_assemble_large_stable_layer_does_not_starve_context():
    compiler = BriefCompiler()
    layers = {
        "stable": "x" * 6000,
        "context": "David is currently in Salem (until Monday, Sept 7).",
        "day": "",
        "moment": "",
    }
    compiled = compiler._assemble(layers)
    assert "in Salem" in compiled


def test_read_layer_day_goes_through_freshness_check(tmp_path, monkeypatch):
    """chat harness repair Phase 3: the compiled brief must never carry
    yesterday's '## Today (...)' heading just because day.md hasn't been
    rolled over yet. compiler._read_layer("day") delegates to
    day_layer.read_fresh_text instead of reading the file directly."""
    import sys
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services.daily_brief.day_layer import day_layer as day_layer_singleton

    day_layer_module = sys.modules["app.services.daily_brief.day_layer"]
    monkeypatch.setattr(day_layer_singleton, "briefs_dir", tmp_path)

    et = ZoneInfo("America/New_York")
    yesterday = datetime(2026, 9, 15, 21, 0, tzinfo=et)
    day_layer_singleton._write_layer(
        "user-1",
        "## Today (Tuesday, September 15)\n\nShoulder day went well.\n",
        effective_date=yesterday,
    )

    monkeypatch.setattr(day_layer_module, "local_now", lambda: datetime(2026, 9, 16, 8, 0, tzinfo=et))

    compiler = BriefCompiler()
    content = compiler._read_layer("user-1", "day")

    assert "## Today (Tuesday, September 15)" not in content
    assert "As of 2026-09-15" in content
    assert "Shoulder day went well." in content
