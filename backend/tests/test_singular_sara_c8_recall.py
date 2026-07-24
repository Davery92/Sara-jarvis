"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C8 extension of `memory.recall()`
with intent and artifact sources.
"""

from datetime import datetime, timezone

import pytest

from app.services import memory_recall


def _row(**kw):
    return kw


class _FakeAsyncDb:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *a, **kw):
        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def mappings(self):
                class _Mappings:
                    def __init__(self, rows):
                        self._rows = rows

                    def all(self):
                        return self._rows

                return _Mappings(self._rows)

        return _Result(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class TestFromIntents:
    @pytest.mark.asyncio
    async def test_maps_rows_and_confidence_by_origin(self, monkeypatch):
        now = datetime.now(timezone.utc)
        rows = [
            _row(intent_id="reminder:r1", kind="reminder", origin="david",
                 status="active", next_step="Pick up dry cleaning", priority=None, updated_at=now),
            _row(intent_id="interest:i1", kind="interest", origin="sara",
                 status="active", next_step="Roman logistics", priority="0.8", updated_at=now),
        ]

        def _fake_factory():
            return lambda: _FakeAsyncDb(rows)

        monkeypatch.setattr("app.db.session.get_async_session_factory", _fake_factory)

        traces = await memory_recall._from_intents("user-1", "dry cleaning", 10)

        assert len(traces) == 2
        by_id = {t["id"]: t for t in traces}
        assert by_id["reminder:r1"]["confidence"] == "confirmed"
        assert by_id["reminder:r1"]["kind"] == "intent"
        assert "Pick up dry cleaning" in by_id["reminder:r1"]["text"]
        assert by_id["interest:i1"]["confidence"] == "inferred"

    @pytest.mark.asyncio
    async def test_query_failure_returns_empty_list(self, monkeypatch):
        def _broken_factory():
            raise ConnectionError("db down")

        monkeypatch.setattr("app.db.session.get_async_session_factory", _broken_factory)

        traces = await memory_recall._from_intents("user-1", "", 10)
        assert traces == []


class TestFromArtifacts:
    @pytest.mark.asyncio
    async def test_maps_rows(self, monkeypatch):
        now = datetime.now(timezone.utc)
        rows = [_row(id="art-1", artifact_type="report", title="Fitness recap", updated_at=now)]

        def _fake_factory():
            return lambda: _FakeAsyncDb(rows)

        monkeypatch.setattr("app.db.session.get_async_session_factory", _fake_factory)

        traces = await memory_recall._from_artifacts("user-1", "fitness", 10)

        assert len(traces) == 1
        assert traces[0]["kind"] == "artifact"
        assert traces[0]["confidence"] == "confirmed"
        assert "Fitness recap" in traces[0]["text"]


class TestRecallIncludesNewKinds:
    @pytest.mark.asyncio
    async def test_all_kinds_includes_intent_and_artifact(self):
        assert "intent" in memory_recall.ALL_KINDS
        assert "artifact" in memory_recall.ALL_KINDS

    @pytest.mark.asyncio
    async def test_recall_fans_out_to_intents_and_artifacts_when_requested(self, monkeypatch):
        async def _fake_intents(user_id, query, per):
            return [{"kind": "intent", "id": "i1", "text": "t", "score": 0.5,
                     "confidence": "confirmed", "provenance": "intent:reminder", "when": None}]

        async def _fake_artifacts(user_id, query, per):
            return [{"kind": "artifact", "id": "a1", "text": "t", "score": 0.5,
                     "confidence": "confirmed", "provenance": "artifact:report", "when": None}]

        monkeypatch.setattr(memory_recall, "_from_intents", _fake_intents)
        monkeypatch.setattr(memory_recall, "_from_artifacts", _fake_artifacts)

        result = await memory_recall.recall(user_id="user-1", query="x", k=5, kinds=["intent", "artifact"])

        assert result["by_kind"] == {"intent": 1, "artifact": 1}
        assert {t["kind"] for t in result["traces"]} == {"intent", "artifact"}

    @pytest.mark.asyncio
    async def test_recall_without_requesting_new_kinds_skips_them(self, monkeypatch):
        called = {"intents": False, "artifacts": False}

        async def _fake_intents(user_id, query, per):
            called["intents"] = True
            return []

        async def _fake_artifacts(user_id, query, per):
            called["artifacts"] = True
            return []

        monkeypatch.setattr(memory_recall, "_from_intents", _fake_intents)
        monkeypatch.setattr(memory_recall, "_from_artifacts", _fake_artifacts)

        await memory_recall.recall(user_id="user-1", query="x", k=5, kinds=["thread"])

        assert called == {"intents": False, "artifacts": False}
