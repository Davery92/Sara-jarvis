"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C1 event-envelope adapter: mapping
correctness, deterministic dedupe (the "replay" property), correlation-ID
propagation from a bound kernel turn, Redis persistence, and — most
importantly — that hooking this into `EventBus.publish()` cannot break the
real publish path it rides alongside.
"""

import fakeredis.aioredis
import pytest

from app.services.event_bus import Event, EventType


def _make_event(**overrides) -> Event:
    defaults = dict(
        event_type=EventType.NOTE_CREATED,
        user_id="user-1",
        payload={"note_id": "n1", "title": "Test note"},
        source="api",
        metadata={},
    )
    defaults.update(overrides)
    return Event(**defaults)


# ==========================================
# Pure mapping
# ==========================================

class TestBuildEnvelope:
    def test_maps_core_fields(self):
        from app.services.event_envelope_adapter import build_envelope

        event = _make_event()
        envelope = build_envelope(event)

        assert envelope.event_id == event.event_id
        assert envelope.user_id == "user-1"
        assert envelope.source == "api"
        assert envelope.kind == "note.created"
        assert envelope.payload == {"note_id": "n1", "title": "Test note"}
        assert envelope.provenance == "api"  # falls back to source
        assert envelope.confidence == 1.0

    def test_metadata_overrides_defaults(self):
        from app.services.event_envelope_adapter import build_envelope

        event = _make_event(metadata={
            "provenance": "ios_calendar_sync",
            "confidence": 0.6,
            "sensitivity": "sensitive",
            "retention_class": "short",
            "causation_id": "turn_prior",
            "source_ref": "note:n1",
        })
        envelope = build_envelope(event)

        assert envelope.provenance == "ios_calendar_sync"
        assert envelope.confidence == 0.6
        assert envelope.sensitivity == "sensitive"
        assert envelope.retention_class == "short"
        assert envelope.causation_id == "turn_prior"
        assert envelope.source_ref == "note:n1"


# ==========================================
# Deterministic dedupe (the "replay" property)
# ==========================================

class TestDedupeKey:
    def test_same_kind_user_payload_yields_same_dedupe_key(self):
        """§C1 exit gate: 'Replaying an event produces the same dedupe...
        outcome.' Two independently-constructed events for 'the same fact'
        (different event_id/timestamp, identical kind+user+payload) must
        dedupe identically."""
        from app.services.event_envelope_adapter import build_envelope

        event_a = _make_event()
        event_b = _make_event()  # fresh event_id/timestamp via defaults

        assert event_a.event_id != event_b.event_id
        envelope_a = build_envelope(event_a)
        envelope_b = build_envelope(event_b)

        assert envelope_a.dedupe_key == envelope_b.dedupe_key

    def test_different_payload_yields_different_dedupe_key(self):
        from app.services.event_envelope_adapter import build_envelope

        envelope_a = build_envelope(_make_event(payload={"note_id": "n1"}))
        envelope_b = build_envelope(_make_event(payload={"note_id": "n2"}))

        assert envelope_a.dedupe_key != envelope_b.dedupe_key

    def test_payload_key_order_does_not_affect_dedupe_key(self):
        from app.services.event_envelope_adapter import build_envelope

        envelope_a = build_envelope(_make_event(payload={"a": 1, "b": 2}))
        envelope_b = build_envelope(_make_event(payload={"b": 2, "a": 1}))

        assert envelope_a.dedupe_key == envelope_b.dedupe_key

    def test_explicit_dedupe_key_in_metadata_wins(self):
        from app.services.event_envelope_adapter import build_envelope

        envelope = build_envelope(_make_event(metadata={"dedupe_key": "custom_key_1"}))
        assert envelope.dedupe_key == "custom_key_1"


# ==========================================
# Correlation propagation
# ==========================================

class TestCorrelationPropagation:
    def test_picks_up_bound_kernel_turn_id(self):
        from app.core.correlation import CorrelationIds, bind_correlation
        from app.services.event_envelope_adapter import build_envelope

        bind_correlation(CorrelationIds(kernel_turn_id="turn_xyz"))
        envelope = build_envelope(_make_event())

        assert envelope.correlation_id == "turn_xyz"

    def test_explicit_metadata_correlation_id_wins_over_bound(self):
        from app.core.correlation import CorrelationIds, bind_correlation
        from app.services.event_envelope_adapter import build_envelope

        bind_correlation(CorrelationIds(kernel_turn_id="turn_xyz"))
        envelope = build_envelope(_make_event(metadata={"correlation_id": "turn_explicit"}))

        assert envelope.correlation_id == "turn_explicit"

    def test_no_bound_correlation_yields_none(self):
        from app.core.correlation import _current
        from app.services.event_envelope_adapter import build_envelope

        token = _current.set(None)
        try:
            envelope = build_envelope(_make_event())
            assert envelope.correlation_id is None
        finally:
            _current.reset(token)


# ==========================================
# Redis persistence
# ==========================================

class TestEnvelopePersistence:
    @pytest.fixture
    def fake_redis(self, monkeypatch):
        import app.services.event_envelope_adapter as adapter

        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

        async def _fake_get_redis():
            return fake

        monkeypatch.setattr(adapter, "_get_redis", _fake_get_redis)
        return fake

    @pytest.mark.asyncio
    async def test_record_and_get_envelope_round_trip(self, fake_redis):
        from app.services.event_envelope_adapter import get_envelope, record_from_event

        event = _make_event()
        recorded = await record_from_event(event)

        fetched = await get_envelope(event.event_id)
        assert fetched is not None
        assert fetched.event_id == recorded.event_id
        assert fetched.dedupe_key == recorded.dedupe_key

    @pytest.mark.asyncio
    async def test_get_envelope_missing_returns_none(self, fake_redis):
        from app.services.event_envelope_adapter import get_envelope

        assert await get_envelope("nonexistent") is None

    @pytest.mark.asyncio
    async def test_recent_envelopes_newest_first(self, fake_redis):
        from app.services.event_envelope_adapter import get_recent_envelopes, record_from_event

        await record_from_event(_make_event(payload={"i": 1}))
        await record_from_event(_make_event(payload={"i": 2}))
        await record_from_event(_make_event(payload={"i": 3}))

        recent = await get_recent_envelopes("user-1", limit=2)
        assert len(recent) == 2
        # Newest (i=3) first, since occurred_at is monotonic creation order.
        assert recent[0].payload["i"] == 3
        assert recent[1].payload["i"] == 2


# ==========================================
# EventBus.publish() must stay unaffected by adapter failures
# ==========================================

class TestPublishWiring:
    @pytest.mark.asyncio
    async def test_publish_still_succeeds_when_adapter_raises(self, monkeypatch):
        from app.services.event_bus import EventBus
        import app.services.event_envelope_adapter as adapter

        bus = EventBus()
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        bus.redis_client = fake

        async def _broken_record(event):
            raise RuntimeError("adapter exploded")

        monkeypatch.setattr(adapter, "record_from_event", _broken_record)

        event = _make_event()
        # Must not raise, and must not reset the (perfectly healthy) redis
        # client just because the *additive* envelope adapter blew up.
        await bus.publish(event)

        assert bus.redis_client is fake
        stored = await fake.get(f"sara:event_log:{event.event_id}")
        assert stored is not None

    @pytest.mark.asyncio
    async def test_publish_records_canonical_envelope(self, monkeypatch):
        from app.services.event_bus import EventBus
        import app.services.event_envelope_adapter as adapter

        bus = EventBus()
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        bus.redis_client = fake
        monkeypatch.setattr(adapter, "_get_redis", lambda: _wrap_fake(fake))

        event = _make_event()
        await bus.publish(event)

        envelope = await adapter.get_envelope(event.event_id)
        assert envelope is not None
        assert envelope.kind == "note.created"

    @pytest.mark.asyncio
    async def test_publish_failure_skips_envelope_recording(self, monkeypatch):
        """If the real publish fails, we must not record a canonical
        envelope for an event that was never actually published."""
        from app.services.event_bus import EventBus
        import app.services.event_envelope_adapter as adapter

        bus = EventBus()

        class _BrokenRedis:
            async def publish(self, *a, **kw):
                raise ConnectionError("redis down")

        bus.redis_client = _BrokenRedis()

        called = {"count": 0}

        async def _record(event):
            called["count"] += 1

        monkeypatch.setattr(adapter, "record_from_event", _record)

        await bus.publish(_make_event())

        assert called["count"] == 0
        assert bus.redis_client is None  # existing failure-handling behavior preserved


async def _wrap_fake(fake):
    return fake
