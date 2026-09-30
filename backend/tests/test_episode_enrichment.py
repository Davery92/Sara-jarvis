"""Unit coverage for incremental episode enrichment (chat harness repair Phase 6).

Covers the pure validation/scoring logic and the debounce+coalescing
scheduler, without needing a real Postgres episode/conversation row.
"""

import types

import fakeredis
import pytest

from app.services.episode_enrichment import (
    EnrichmentValidationError,
    _apply_enrichment,
    _validate_enrichment,
)


class FakeEpisode:
    def __init__(self, role="user", content="hi", importance=0.5):
        self.role = role
        self.content = content
        self.importance = importance
        self.base_importance = None
        self.emotional_tone = None
        self.topics = None
        self.emotion_metadata = None


# ---------------------------------------------------------------------------
# _validate_enrichment
# ---------------------------------------------------------------------------

def test_validate_enrichment_accepts_well_formed_response():
    parsed = {"messages": [{"index": 0, "scores": {"importance": 0.7}}, {"index": 1}]}
    validated = _validate_enrichment(parsed, expected_count=2)
    assert len(validated) == 2


def test_validate_enrichment_rejects_non_dict():
    with pytest.raises(EnrichmentValidationError):
        _validate_enrichment(["not", "a", "dict"], expected_count=1)


def test_validate_enrichment_rejects_missing_messages_key():
    with pytest.raises(EnrichmentValidationError):
        _validate_enrichment({"no_messages_here": []}, expected_count=1)


def test_validate_enrichment_drops_out_of_range_indices():
    parsed = {"messages": [{"index": 0}, {"index": 99}, {"index": -1}]}
    validated = _validate_enrichment(parsed, expected_count=1)
    assert [item["index"] for item in validated] == [0]


def test_validate_enrichment_drops_duplicate_indices_keeping_first():
    parsed = {"messages": [{"index": 0, "topics": ["a"]}, {"index": 0, "topics": ["b"]}]}
    validated = _validate_enrichment(parsed, expected_count=1)
    assert len(validated) == 1
    assert validated[0]["topics"] == ["a"]


def test_validate_enrichment_raises_when_nothing_survives():
    parsed = {"messages": [{"index": 5}]}
    with pytest.raises(EnrichmentValidationError):
        _validate_enrichment(parsed, expected_count=1)


# ---------------------------------------------------------------------------
# _apply_enrichment
# ---------------------------------------------------------------------------

def test_apply_enrichment_writes_composite_score():
    episodes = [FakeEpisode()]
    items = [{
        "index": 0,
        "emotion": {"primary_emotion": "excited", "intensity": 0.8, "sentiment": "positive"},
        "topics": ["fitness"],
        "scores": {"importance": 1.0, "affect": 1.0, "novelty": 1.0, "taskness": 1.0},
    }]

    updated = _apply_enrichment(episodes, items)

    assert updated == 1
    ep = episodes[0]
    assert ep.importance == pytest.approx(1.0)
    assert ep.base_importance == pytest.approx(1.0)
    assert ep.emotion_metadata["scored_by"] == "incremental_batch_llm"
    assert "fitness" in __import__("json").loads(ep.topics)


def test_apply_enrichment_clamps_out_of_range_scores():
    episodes = [FakeEpisode()]
    items = [{"index": 0, "scores": {"importance": 5.0, "affect": -9.0, "novelty": -1.0, "taskness": 2.0}}]

    _apply_enrichment(episodes, items)

    meta = episodes[0].emotion_metadata
    assert meta["importance_score"] == 1.0
    assert meta["affect_score"] == -1.0
    assert meta["novelty_score"] == 0.0
    assert meta["taskness_score"] == 1.0


# ---------------------------------------------------------------------------
# schedule_conversation_enrichment: debounce + coalescing
# ---------------------------------------------------------------------------

def test_schedule_enrichment_debounces_repeated_calls(monkeypatch):
    from app.tasks import episode_enrichment as task_mod

    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.redis.get_redis_sync", lambda: fake)

    calls = []
    monkeypatch.setattr(
        task_mod.enrich_conversation_task,
        "apply_async",
        lambda args, countdown: calls.append((args, countdown)),
    )

    task_mod.schedule_conversation_enrichment("conv-1", "user-1")
    task_mod.schedule_conversation_enrichment("conv-1", "user-1")
    task_mod.schedule_conversation_enrichment("conv-1", "user-1")

    assert len(calls) == 1
    assert calls[0][0] == ["conv-1", "user-1"]
    assert calls[0][1] == task_mod.IDLE_DEBOUNCE_SECONDS


def test_schedule_enrichment_allows_separate_conversations(monkeypatch):
    from app.tasks import episode_enrichment as task_mod

    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.redis.get_redis_sync", lambda: fake)

    calls = []
    monkeypatch.setattr(
        task_mod.enrich_conversation_task,
        "apply_async",
        lambda args, countdown: calls.append(args),
    )

    task_mod.schedule_conversation_enrichment("conv-1", "user-1")
    task_mod.schedule_conversation_enrichment("conv-2", "user-1")

    assert len(calls) == 2


def test_schedule_enrichment_never_raises_when_redis_unavailable(monkeypatch):
    from app.tasks import episode_enrichment as task_mod

    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis_sync", _boom)
    # Must not raise — scheduling is best-effort and sits in the chat response path.
    task_mod.schedule_conversation_enrichment("conv-1", "user-1")
