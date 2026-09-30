"""Convention-readiness: note capture must not need an imperative verb, and
note search must return findable, bounded results.

Both behaviours are the primary workflow for 2026-09-27 (capture and retrieve
notes about people and sessions), and both were broken in different ways:

* Capture: the execution-boundary gate required a verb from
  `ACTION_INTENT_VERBS`. Seven of nine realistic "I just met someone" phrasings
  carry no such verb, so the write was refused and David had to repeat himself.
* Recall: `notes_search` returned every hit's FULL content, so a default
  limit=10 search produced ~19,000 chars against a 9,000-char inline ceiling —
  upstream replaced it with `content[:3000]`, hiding hits 3..10 while telling
  the model not to report an empty result.

These are deterministic; no model requests.
"""
import pytest

from app.services.tool_mutation import (
    is_mutating_tool,
    APPEND_ONLY_CAPABLE,
    CAPTURE_TOOLS,
    gate_mutating_tools,
    has_action_intent,
    is_additive_capture_call,
)
from app.tools.notes import (
    NOTES_SNIPPET_CHARS,
    NOTES_VECTOR_MIN_SIMILARITY,
    _query_terms,
    _snippet,
)


# The exact phrasings measured against the pre-fix gate. Every one of these is
# a genuine request to write something down.
CAPTURE_PHRASINGS = [
    "Remember that I met Dana from Acme, she runs their platform team",
    "I just met Dana from Acme - she runs their platform team. Keep that somewhere.",
    "Note that the keynote moved to hall C",
    "Dana from Acme: platform team lead, wants a follow-up about pricing",
    "Jot down that Marcus at Contoso is hiring two SREs",
    "Take a note about the session on vector search",
    "FYI I talked to Priya from Globex about the migration",
    "Add a note that Dana runs the platform team",
    "Make a note about Dana from Acme",
]


class TestCaptureIsNotAnImperative:
    @pytest.mark.parametrize("message", CAPTURE_PHRASINGS)
    def test_notes_create_survives_selection_for_every_capture_phrasing(self, message):
        """The regression this fixes: the tool was dropped before the model saw it."""
        schemas = [{"type": "function", "function": {"name": "notes_create"}}]
        kept, dropped = gate_mutating_tools(schemas, message)
        assert dropped == [], f"notes_create dropped for: {message!r}"
        assert len(kept) == 1

    @pytest.mark.parametrize("message", CAPTURE_PHRASINGS)
    def test_execution_authorizes_notes_create_for_every_capture_phrasing(self, message):
        """Authorization now comes from the call's shape, not the verb list."""
        assert is_additive_capture_call("notes_create", {"title": "Dana", "content": "x"}) is True

    def test_most_of_those_phrasings_genuinely_lack_an_action_verb(self):
        """Guards the premise: this is not a no-op exemption.

        If a future change taught has_action_intent these phrasings, the
        exemption would be redundant rather than load-bearing — worth knowing.
        """
        without = [m for m in CAPTURE_PHRASINGS if not has_action_intent(m)]
        assert len(without) >= 5, (
            "has_action_intent now accepts most capture phrasings; the capture "
            f"exemption may no longer be what makes them work (only {len(without)} lack a verb)"
        )

    def test_append_only_edit_is_a_capture(self):
        assert is_additive_capture_call("notes_edit", {"note_id": "n1", "append_text": "also hiring"}) is True

    def test_a_narrow_deletion_is_NOT_exempt(self):
        """Narrowness is not authorization.

        `remove_text` deletes exactly one matched span and refuses on
        zero/multiple matches, and was briefly exempt on that basis. A precise
        deletion is still a deletion: it needs David's own authorization, not a
        structural argument that it can only destroy a little. Reverted
        2026-09-27 on his instruction.
        """
        assert is_additive_capture_call(
            "notes_edit", {"note_id": "n1", "remove_text": "runs their platform team"}
        ) is False

    @pytest.mark.parametrize("args", [
        {"note_id": "n1", "content": "a whole new body"},
        {"note_id": "n1", "title": "renamed"},
        {"note_id": "n1", "remove_text": "the rain jacket"},
        {"note_id": "n1", "append_text": "x", "content": "full rewrite too"},
        {"note_id": "n1", "append_text": "x", "remove_text": "and a deletion"},
        {"note_id": "n1", "append_text": "x", "title": "renamed too"},
        {"note_id": "n1", "append_text": "   "},
        {"note_id": "n1"},
    ])
    def test_anything_that_can_lose_text_is_not_a_capture(self, args):
        """Only a pure append is exempt — including when a deletion or a
        rewrite is smuggled in alongside one."""
        assert is_additive_capture_call("notes_edit", args) is False

    @pytest.mark.parametrize("tool", [
        "standing_order_create", "reminders_cancel", "notes_delete",
        "calendar_create_event", "email_send", "merge_notes",
    ])
    def test_consequential_tools_are_not_captures(self, tool):
        assert is_additive_capture_call(tool, {"anything": "at all"}) is False

    def test_a_hypothetical_still_cannot_create_a_standing_order(self):
        """The J11 incident must stay closed — this fix must not widen it."""
        hypothetical = "I'm thinking about turning on the porch light when I get back"
        assert has_action_intent(hypothetical) is False
        assert is_additive_capture_call("standing_order_create", {"trigger": "arrive"}) is False
        schemas = [{"type": "function", "function": {"name": "standing_order_create"}}]
        kept, dropped = gate_mutating_tools(schemas, hypothetical)
        assert dropped == ["standing_order_create"]
        assert kept == []

    def test_unparseable_arguments_are_not_a_capture(self):
        """Fails to the gate, never past it."""
        for bad in (None, "a string", 42, []):
            assert is_additive_capture_call("notes_edit", bad) is False

    def test_capture_sets_do_not_overlap(self):
        assert not (CAPTURE_TOOLS & APPEND_ONLY_CAPABLE)


class TestCorrectionWorkflowToolAvailability:
    """`remember_about_david` is no longer offered (registry `personal_knowledge`).

    It measured 0 for 4 live — 2 refused at the execution boundary, 2
    `action_receipt` status=failed — and because it reads as the obvious
    "remember this" tool the model chose it over `notes_create`/`notes_edit` on
    both capture and correction turns, persisting nothing.
    """

    def test_the_broken_write_tool_is_not_offered(self):
        from app.tools.registry import tool_registry
        groups = tool_registry.get_tool_groups() if hasattr(tool_registry, "get_tool_groups") else None
        if groups is None:  # shape differs across versions; assert on the source of truth
            import app.tools.registry as reg
            import inspect
            src = inspect.getsource(reg)
            assert "'tools': ['query_david_knowledge']" in src
            return
        pk = groups.get("personal_knowledge", {})
        assert "remember_about_david" not in pk.get("tools", [])
        assert "query_david_knowledge" in pk.get("tools", [])

    def test_the_read_side_is_preserved(self):
        """Removing the write tool must not blind Sara to what the PKG holds."""
        assert is_mutating_tool("query_david_knowledge") is False

    def test_it_stays_registered_and_executable_if_explicitly_named(self):
        """Only the OFFERED menu changed — nothing structural was deleted, so
        restoring it later is a one-line revert."""
        from app.tools.registry import tool_registry
        assert "remember_about_david" in tool_registry.tools


class TestReadToolsAreNotGated:
    """Live validation 2026-09-27, conversation B turn 2: a plain recall
    question ("What was I supposed to do about the Contoso guy?") had
    `query_david_knowledge` refused by the execution boundary as a mutating
    tool. Unrecognized names default to mutating, which also caught read-only
    tools whose names use none of the listed read verbs.
    """

    @pytest.mark.parametrize("name", [
        "query_david_knowledge",
        "pattern_query",
        "diagnostics_explain",
    ])
    def test_read_only_tools_are_classified_read_only(self, name):
        assert is_mutating_tool(name) is False

    @pytest.mark.parametrize("name", [
        "notes_create", "notes_delete", "reminders_cancel", "standing_order_create",
        "daily_task_create", "dispatch_agent_task", "cancel_agent_task",
        "remember_about_david",
    ])
    def test_genuine_writes_stay_mutating(self, name):
        assert is_mutating_tool(name) is True

    def test_a_mutating_token_still_wins_over_a_read_token(self):
        """The read tokens only decide a name carrying no mutating token, so
        adding "query" cannot un-gate a write that mentions querying."""
        assert is_mutating_tool("query_and_delete_notes") is True
        assert is_mutating_tool("explain_and_update_plan") is True


class TestSearchQueryTerms:
    def test_a_natural_question_yields_its_discriminating_terms(self):
        terms = _query_terms("who did I meet from Acme?")
        assert "acme" in terms
        assert "who" not in terms and "did" not in terms and "from" not in terms

    def test_longest_terms_come_first(self):
        terms = _query_terms("the platform team lead at Acme Corporation")
        assert terms == sorted(terms, key=len, reverse=True)
        assert terms[0] == "corporation"

    def test_terms_are_capped_and_deduplicated(self):
        terms = _query_terms("acme acme ACME platform platform vector search pricing keynote hallway")
        assert len(terms) <= 6
        assert len(terms) == len(set(terms))

    def test_a_query_of_only_stopwords_yields_nothing(self):
        """Must not crash or degenerate into matching everything."""
        assert _query_terms("what did I say about that?") == []

    def test_empty_query_is_safe(self):
        assert _query_terms("") == []
        assert _query_terms(None) == []


class TestSearchSnippets:
    def test_a_short_note_is_returned_whole(self):
        body = "Dana - platform team lead at Acme."
        assert _snippet(body, ["acme"]) == body

    def test_a_long_note_is_bounded(self):
        body = "x" * 5000
        out = _snippet(body, [])
        assert len(out) <= NOTES_SNIPPET_CHARS + 2  # room for the ellipses

    def test_the_snippet_centres_on_why_the_note_matched(self):
        """A name buried deep must be visible in the excerpt — the whole point.

        A leading content[:400] would show only filler here.
        """
        body = ("filler. " * 200) + "Dana runs the Acme platform team. " + ("tail. " * 200)
        out = _snippet(body, ["dana"])
        assert "Dana runs the Acme platform team" in out
        assert out.startswith("…")

    def test_no_terms_falls_back_to_the_opening(self):
        body = "Opening sentence here. " + ("x" * 5000)
        out = _snippet(body, [])
        assert out.startswith("Opening sentence here.")

    def test_a_term_that_does_not_appear_falls_back_safely(self):
        body = "Opening sentence here. " + ("x" * 5000)
        out = _snippet(body, ["nonexistent"])
        assert out.startswith("Opening sentence here.")

    def test_empty_content_is_safe(self):
        assert _snippet(None, ["x"]) == ""
        assert _snippet("", ["x"]) == ""

    def test_ten_hits_stay_well_under_the_inline_ceiling(self):
        """The actual regression: 10 full notes were ~19,000 chars against a
        9,000-char ceiling, so hits 3..10 were dropped from the model's view."""
        realistic_note = "y" * 8225  # the measured mean content length
        payload = sum(len(_snippet(realistic_note, [])) for _ in range(10))
        assert payload < 9000, f"10 snippets still exceed the inline ceiling: {payload}"


class TestVectorFloor:
    def test_the_floor_is_a_real_threshold(self):
        """A floor of 0 would restore "return the nearest 10 rows regardless"."""
        assert 0.0 < NOTES_VECTOR_MIN_SIMILARITY < 1.0
