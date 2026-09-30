"""Hard final-boundary clip for the live context block (chat harness repair
Phase 2). Before this, LIVE_CONTEXT_CHAR_BUDGET only produced a warning —
the engaged block (~4,400 chars) and the post-engaged tail (~16,000 chars)
each had their own cap, but nothing capped their sum, so a turn could carry
8,200-10,555 chars of live context despite the configured 4,500-char
"budget" in the log line.
"""
from app.services.context_budget import enforce_live_context_budget


def test_text_under_budget_is_untouched():
    text = "short context"
    clipped, raw = enforce_live_context_budget(text, budget_chars=4500)
    assert clipped == text
    assert raw == len(text)


def test_text_over_budget_is_clipped_to_the_budget():
    text = "x" * 10000
    clipped, raw = enforce_live_context_budget(text, budget_chars=4500)
    assert raw == 10000
    assert len(clipped) <= 4500


def test_clip_lands_on_a_paragraph_boundary_not_mid_word():
    para1 = "First paragraph. " * 100  # ~1700 chars
    para2 = "Second paragraph that would otherwise be sliced mid-sentence here. " * 40
    text = para1 + "\n\n" + para2
    clipped, raw = enforce_live_context_budget(text, budget_chars=1800)
    assert raw == len(text)
    assert len(clipped) <= 1800
    # Cut at the paragraph break, not mid-word inside para2.
    assert clipped.rstrip().endswith(".") or clipped == para1.strip()
    assert not clipped.endswith(("Second paragraph that would otherwise be sliced mid-sentence her",))


def test_sum_of_independently_budgeted_sections_still_gets_capped():
    """The exact failure mode: two upstream sections each respect their own
    cap (engaged ~4,400 chars, tail ~16,000 chars) but nothing caps the sum
    before this — reproduces the 8,200-10,555 char turns from 2026-09-16."""
    engaged_block = "y" * 4400
    post_engaged_tail = "z" * 6000  # under its own 16,000-char cap
    combined = engaged_block + "\n\n" + post_engaged_tail

    clipped, raw = enforce_live_context_budget(combined, budget_chars=4500)

    assert raw == len(combined)
    assert raw > 4500  # the bug: each piece was "in budget" but the sum wasn't
    assert len(clipped) <= 4500


def test_empty_text_is_handled():
    clipped, raw = enforce_live_context_budget("", budget_chars=4500)
    assert clipped == ""
    assert raw == 0
