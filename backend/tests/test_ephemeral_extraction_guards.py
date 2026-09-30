"""Living-world-context plan acceptance matrix: 'Ephemeral chat and two
users | No durable ephemeral-world writes... For ephemeral chat, check all
durable side effects, including extraction, enrichment, and context
updates.'

test_ephemeral_no_world_state_writes.py already proves episode storage
(and the world-event emission attached to it) is skipped. This file covers
three MORE durable, content-derived side effects inside process_chat()
that were unguarded before this session: commitment/thread extraction,
lesson extraction from feedback, and Sara's emotional-state update — each
reads request.messages/response_content directly and persists something.

process_chat() is a closure deep inside the SSE streaming endpoint with no
seams for direct unit invocation (auth, streaming, a live DB session, and
the whole chat_with_tools loop all sit in front of it). Source-inspection
is the same pattern this codebase already uses for an invariant like this
— see test_chat_tool_loop.py's TestSummarizeToolResultsIsNotUserFacing —
and is honest about what it proves: the guard is present in the right
place, not that a live ephemeral turn was observed end-to-end.
"""
import inspect
import re

from app import main_simple as ms


def _process_chat_source() -> str:
    source = inspect.getsource(ms)
    start = source.index("async def process_chat():")
    # process_chat is a nested closure; bound its source by the next
    # top-level (4-space-indented) def after it, so a change elsewhere in
    # the file can't silently make this test check the wrong span.
    rest = source[start:]
    m = re.search(r"\n            async def \w+\(", rest[1:])
    end = m.start() + 1 if m else len(rest)
    return rest[:end]


class TestEphemeralGuardsOnPostTurnExtraction:
    def test_thread_extraction_is_guarded(self):
        src = _process_chat_source()
        idx = src.index("extract_from_conversation_bg")
        window = src[max(0, idx - 900):idx]
        assert "if not request.ephemeral:" in window

    def test_lesson_extraction_self_learning_loop_is_guarded(self):
        src = _process_chat_source()
        # Not .index("create_lesson_from_feedback") — that also matches an
        # explanatory code comment mentioning the function by name just
        # above the guard, so it isn't a reliable anchor. The import line
        # is unambiguous.
        idx = src.index("from app.services.lesson_extractor import create_lesson_from_feedback")
        window = src[max(0, idx - 900):idx]
        assert "if not request.ephemeral:" in window

    def test_emotional_state_update_is_guarded(self):
        src = _process_chat_source()
        idx = src.index("_update_emotional_state_from_chat")
        window = src[max(0, idx - 900):idx]
        assert "if not request.ephemeral:" in window

    def test_conversation_enrichment_scheduling_is_guarded(self):
        src = _process_chat_source()
        idx = src.index("schedule_conversation_enrichment")
        window = src[max(0, idx - 900):idx]
        assert "if not request.ephemeral:" in window
