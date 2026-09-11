"""Retrieval-based tool selection (harness rebuild Phase 2).

The failure this replaces: `ToolIntentClassifier.classify_with_context` is
first-match keyword routing, so on 2026-09-11 "download those attachments and
put them in a folder" matched `folder` → NOTES, and the tool that files
attachments was never loaded. Two turns later the sticky append-only category
list had grown to 94 schemas and the model called `web_search` to find out
what it could do.

These tests run against a deterministic lexical fake embedder rather than
bge-m3: the point under test is the selection machinery (floors, family
boost, ordering, cap), not the embedding model. The fake's cosine scale is
much lower than bge-m3's, so the tests pass their own thresholds.
"""

import math
import re

import pytest

from app.services import tool_retrieval as tr
from app.services.tool_retrieval import (
    CORE_TOOLS,
    MAX_TOOLS_PER_CALL,
    select_chat_tools,
    tool_names,
)

# Words that appear in half the tool descriptions and carry no signal.
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for", "from",
    "get", "he", "his", "if", "in", "is", "it", "me", "not", "of", "on", "or",
    "the", "them", "then", "this", "those", "to", "up", "use", "used", "user",
    "when", "with", "you", "your", "david", "sara", "i", "my", "that", "it's",
    "actually", "just", "some", "any", "all", "one", "call", "tool", "tools",
}

_DIM = 8192
# Collision-free token -> dimension assignment. Hashing into a fixed space gave
# unrelated text a nonzero cosine, which made "does nonsense retrieve nothing?"
# untestable; a growing vocab has no collisions and cosine is invariant to which
# index a token lands on.
_VOCAB: dict = {}


def _tokens(text: str):
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 2 and t not in _STOP
    }


def _fake_vector(text: str):
    """Sparse L2-normalized bag of words. Cosine between two of these is
    |overlap| / sqrt(|A|*|B|) — enough to rank tools by word overlap."""
    vec = [0.0] * _DIM
    for t in _tokens(text):
        idx = _VOCAB.get(t)
        if idx is None:
            if len(_VOCAB) >= _DIM:
                continue
            idx = _VOCAB[t] = len(_VOCAB)
        vec[idx] = 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """Swap bge-m3 for the lexical fake and give each test a clean index."""
    async def _embed(text: str):
        return _fake_vector(text)

    monkeypatch.setattr("app.services.embeddings.get_embedding", _embed)
    # Redis would otherwise hand back a real bge-m3 index built at startup.
    monkeypatch.setattr(
        tr._ToolIndex, "_load_from_redis", lambda self, sig: _none(), raising=True
    )
    monkeypatch.setattr(
        tr._ToolIndex, "_save_to_redis", lambda self, sig, vecs: _none(), raising=True
    )
    index = tr._ToolIndex()
    monkeypatch.setattr(tr, "ToolIndex", index)
    return index


async def _none():
    return None


# The fake's absolute scale is ~0.1-0.4 where bge-m3 is ~0.4-0.75. Measured
# against this registry: a real capability match lands 0.29-0.41, incidental
# word overlap lands under 0.16.
FAKE_MIN = 0.20
FAKE_MARGIN = 0.15


async def _retrieve(index, query, k=6, exclude=()):
    # The fake's median score is ~0 (most tools share no words with a query),
    # so the relative gap is effectively the top score itself.
    return await index.retrieve(
        query, k=k, exclude=exclude,
        min_score=FAKE_MIN, margin=FAKE_MARGIN, min_rel_gap=FAKE_MIN,
    )


@pytest.mark.asyncio
class TestRetrieval:
    async def test_attachments_into_a_folder_still_has_the_email_family(self, fake_embedder):
        """The literal Sept 11 turn 3 sentence. Keyword routing sent this to
        NOTES because of the word 'folder', and the turn ran with zero email
        tools loaded. The email family is now unconditional core, so the tool
        list carries it no matter what any classifier thinks the turn is about.
        (Phase 4 extends this to `files_to_studio`.)"""
        retrieved = await _retrieve(
            fake_embedder,
            "Can you actually download those attachments and put them in a folder for me? "
            "Do you have the capability?",
            exclude=set(CORE_TOOLS),
        )
        names = tool_names(select_chat_tools(CORE_TOOLS, retrieved, []))
        for expected in ("email_search", "email_read", "email_attachment_read"):
            assert expected in names, names

    async def test_canvas_note_request_reaches_canvas_open_note(self, fake_embedder):
        names = await _retrieve(fake_embedder, "open my AMS360 note in the canvas")
        assert "canvas_open_note" in names, names

    async def test_lights_request_reaches_home_light_control(self, fake_embedder):
        names = await _retrieve(fake_embedder, "turn off the kitchen lights please")
        assert "home_light_control" in names, names

    async def test_filler_turn_retrieves_nothing(self, fake_embedder):
        assert await _retrieve(fake_embedder, "Well?") == []
        assert await _retrieve(fake_embedder, "Okay guess not") == []

    async def test_nothing_relevant_returns_empty_not_least_bad(self, fake_embedder):
        # No tool is about this; the absolute floor must win over the ranking.
        names = await _retrieve(
            fake_embedder, "zzqqxx blorptaculous frimwangle spoonhenge quibblenaut"
        )
        assert names == [], names

    async def test_excluded_names_never_come_back(self, fake_embedder):
        names = await _retrieve(
            fake_embedder, "turn off the kitchen lights please",
            exclude={"home_light_control"},
        )
        assert "home_light_control" not in names

    async def test_k_is_respected(self, fake_embedder):
        names = await _retrieve(
            fake_embedder, "search my email for the invoice attachments", k=3
        )
        assert len(names) <= 3


@pytest.mark.asyncio
class TestTurnAssembly:
    async def test_three_consecutive_intents_never_exceed_the_cap(self, fake_embedder):
        sticky: list = []
        turns = [
            "turn off the kitchen lights please",
            "open my AMS360 note in the canvas",
            "search my email for the invoice attachments and read the first one",
        ]
        for t in turns:
            retrieved = await _retrieve(
                fake_embedder, t, exclude=set(CORE_TOOLS) | set(sticky)
            )
            for n in retrieved:
                if n not in sticky:
                    sticky.append(n)
            schemas = select_chat_tools(CORE_TOOLS, retrieved, sticky)
            names = tool_names(schemas)
            assert len(names) <= MAX_TOOLS_PER_CALL, names
            # Prefix stability: the core is always first, in the same order,
            # which is what keeps MTPLX's prompt cache warm across turns.
            assert names[: len(CORE_TOOLS)] == list(CORE_TOOLS)

    async def test_index_rebuilds_only_when_the_registry_changes(self, fake_embedder):
        await fake_embedder.ensure_built()
        sig = fake_embedder._signature
        await fake_embedder.ensure_built()
        assert fake_embedder._signature == sig

    async def test_median_gap_is_what_rejects_filler(self, fake_embedder):
        """Guards the constant that actually does the discriminating.

        Measured against bge-m3 and this registry on 2026-09-11:
        filler and nonsense queries produce a top-minus-median gap of
        0.087-0.093; real requests produce 0.158-0.320. MIN_REL_GAP sits
        between them. If someone lowers it, filler turns start loading tools
        again — the Sept 11 turn-4 failure.
        """
        assert 0.10 <= tr.MIN_REL_GAP <= 0.15
        # An absolute floor alone cannot do this job: "Good morning Sara"
        # scored 0.576 and a genuine lights request 0.655.
        assert tr.MIN_ABS_SCORE < 0.576

    async def test_every_registered_tool_is_indexed(self, fake_embedder):
        from app.tools.registry import tool_registry

        await fake_embedder.ensure_built()
        registered = {
            (s.get("function") or {}).get("name")
            for s in tool_registry.get_openai_schemas()
        }
        assert registered - set(fake_embedder._vectors) == set()
