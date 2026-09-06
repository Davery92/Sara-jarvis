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
