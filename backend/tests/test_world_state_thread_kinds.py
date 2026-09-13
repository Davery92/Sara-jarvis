"""The interpreter may not invent thread kinds.

2026-09-11: the interpreter read David's own chat turns and opened five
threads with kinds it made up — `feature_gap` x2, `feature_request` x2,
`action_item` x1. THREAD_KIND_CLOSERS has no entry for any of them, so
nothing in the system could close them, and the weekly wiring check reported
them as permanent findings every Sunday until 2026-09-13.
"""
from app.services.world_state.thread_kinds import (
    DEFAULT_INTERPRETED_KIND,
    INTERPRETED_THREAD_KINDS,
    THREAD_KIND_CLOSERS,
    coerce_interpreted_kind,
)


class TestCoerceInterpretedKind:
    def test_the_kinds_that_actually_happened_become_follow_up(self):
        for invented in ("feature_request", "feature_gap", "action_item"):
            assert coerce_interpreted_kind(invented) == "follow_up"

    def test_hyphen_drift_is_normalized_not_rejected(self):
        assert coerce_interpreted_kind("follow-up") == "follow_up"

    def test_legal_kinds_pass_through(self):
        for kind in INTERPRETED_THREAD_KINDS:
            assert coerce_interpreted_kind(kind) == kind

    def test_missing_kind_defaults(self):
        assert coerce_interpreted_kind(None) == "follow_up"
        assert coerce_interpreted_kind("") == "follow_up"
        assert coerce_interpreted_kind("   ") == "follow_up"

    def test_case_and_whitespace_are_not_a_new_kind(self):
        assert coerce_interpreted_kind("  COMMITMENT  ") == "commitment"

    def test_a_long_string_cannot_become_an_uncloseable_kind(self):
        assert coerce_interpreted_kind("x" * 500) == DEFAULT_INTERPRETED_KIND


class TestEveryInterpretedKindCanBeClosed:
    def test_interpreted_kinds_are_a_subset_of_the_closers(self):
        """The whole invariant in one line: if the interpreter can open it,
        something must be able to close it."""
        assert set(INTERPRETED_THREAD_KINDS) <= set(THREAD_KIND_CLOSERS)

    def test_the_default_has_a_closer(self):
        assert THREAD_KIND_CLOSERS[DEFAULT_INTERPRETED_KIND]

    def test_every_registered_kind_names_its_closer(self):
        for kind, closer in THREAD_KIND_CLOSERS.items():
            assert closer, f"{kind} has no closer"


class TestInterpreterParseClamps:
    def test_an_invented_kind_in_model_output_becomes_follow_up(self):
        """interpreter._clean_result is the first of the two doors."""
        from types import SimpleNamespace

        from app.services.world_state import interpreter

        event = SimpleNamespace(
            kind="chat.user_turn_stored",
            aggregate_id="conv-1",
            source_ref=None,
            event_id="evt-1",
            payload={},
        )
        parsed = interpreter._clean_result(
            {
                "headline": "Studio download gap",
                "threads": [
                    {"thread_key": "t1", "kind": "action_item", "title": "Execute Phase 7 Idempotency Check"},
                    {"thread_key": "t2", "kind": "feature_request", "title": "Implement studio downloads"},
                    {"thread_key": "t3", "kind": "commitment", "title": "Send Laura the quote"},
                ],
            },
            event,
        )
        kinds = [t["kind"] for t in parsed["threads"]]
        assert kinds == ["follow_up", "follow_up", "commitment"]


class TestReducerClamps:
    def test_the_reducer_only_clamps_interpreted_events(self):
        """Trusted producers open `prep`, `meeting`, `plan`; only kinds an LLM
        chose get coerced. Guard the condition, not the whole reduce path."""
        import inspect

        from app.services.world_state import reducer

        source = inspect.getsource(reducer._reduce_domain)
        assert 'from_interpretation = kind == "world.interpretation.completed"' in source
        assert "coerce_interpreted_kind(item.get(\"kind\")) if from_interpretation" in source
