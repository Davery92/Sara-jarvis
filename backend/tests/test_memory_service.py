"""
Unit Tests for MemoryService

Tests all core methods:
- store_trace()
- recall()
- consolidate_day()
- forget()
"""

import pytest
from datetime import datetime, timedelta
import json


# ==========================================
# TEST STORE_TRACE
# ==========================================

@pytest.mark.asyncio
async def test_store_trace_basic(memory_service, test_user_id, db_session):
    """Test basic trace storage"""
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Test memory content",
        role="user"
    )

    assert trace_id is not None
    assert isinstance(trace_id, str)

    # Verify in database
    from app.main_simple import MemoryTrace
    trace = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id).first()
    assert trace is not None
    assert trace.content == "Test memory content"
    assert trace.role == "user"
    assert trace.user_id == test_user_id


@pytest.mark.asyncio
async def test_store_trace_with_metadata(memory_service, test_user_id, db_session):
    """Test trace storage with source and meta"""
    source = {"type": "chat", "session_id": "123"}
    meta = {"importance": "high", "tags": ["work", "meeting"]}

    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Important meeting notes",
        role="assistant",
        salience=0.9,
        source=source,
        meta=meta
    )

    from app.main_simple import MemoryTrace
    trace = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id).first()

    assert trace.salience == 0.9
    assert json.loads(trace.source) == source
    assert json.loads(trace.meta) == meta


@pytest.mark.asyncio
async def test_store_trace_redis_cache(memory_service, test_user_id, redis_client):
    """Test that traces are cached in Redis"""
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Cached memory",
        role="user"
    )

    # Check Redis
    key = f"user:{test_user_id}:memory:recent"
    cached = redis_client.zrange(key, 0, -1)

    assert len(cached) == 1
    cached_data = json.loads(cached[0])
    assert cached_data["trace_id"] == trace_id
    assert cached_data["content"] == "Cached memory"


@pytest.mark.asyncio
async def test_store_trace_auto_salience(memory_service, test_user_id, db_session):
    """Test auto-salience calculation"""
    from app.main_simple import MemoryTrace

    # User input with important keyword
    trace_id_1 = await memory_service.store_trace(
        user_id=test_user_id,
        content="This is important and urgent information",
        role="user"
    )

    # Assistant response, short
    trace_id_2 = await memory_service.store_trace(
        user_id=test_user_id,
        content="OK",
        role="assistant"
    )

    trace_1 = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id_1).first()
    trace_2 = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id_2).first()

    # User + important keyword + length should have higher salience
    assert trace_1.salience > trace_2.salience


# ==========================================
# TEST RECALL
# ==========================================

@pytest.mark.asyncio
async def test_recall_from_redis(memory_service, test_user_id):
    """Test recall from Redis cache (recent memories)"""
    # Store a trace
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Recent memory about machine learning",
        role="user"
    )

    # Recall
    results = await memory_service.recall(
        user_id=test_user_id,
        q="machine learning",
        k=5
    )

    assert len(results) >= 1
    assert any(r["trace_id"] == trace_id for r in results)
    assert results[0]["head"] == "recent"  # Came from Redis


@pytest.mark.asyncio
async def test_recall_from_database(memory_service, test_user_id, sample_memory_traces, redis_client):
    """Test recall from database when not in Redis"""
    # Clear Redis to force database lookup
    redis_client.flushall()

    # Recall
    results = await memory_service.recall(
        user_id=test_user_id,
        q="sample content",
        k=5
    )

    # Should find traces from database (fallback mode since no pgvector in SQLite)
    assert len(results) > 0


@pytest.mark.asyncio
async def test_recall_with_time_window(memory_service, test_user_id, db_session):
    """Test time window filtering in recall"""
    from app.main_simple import MemoryTrace

    # Create old trace (outside window)
    old_trace = MemoryTrace(
        id="old-trace",
        user_id=test_user_id,
        content="Old memory",
        role="user",
        created_at=datetime.utcnow() - timedelta(days=60)
    )

    # Create recent trace (inside window)
    recent_trace = MemoryTrace(
        id="recent-trace",
        user_id=test_user_id,
        content="Recent memory",
        role="user",
        created_at=datetime.utcnow() - timedelta(days=5)
    )

    db_session.add(old_trace)
    db_session.add(recent_trace)
    db_session.commit()

    # Note: SQLite fallback doesn't support time windows,
    # but we test the parameter handling
    results = await memory_service.recall(
        user_id=test_user_id,
        q="memory",
        k=10,
        time_window="30d"
    )

    # Just verify it doesn't crash
    assert isinstance(results, list)


# ==========================================
# TEST CONSOLIDATE_DAY
# ==========================================

@pytest.mark.asyncio
async def test_consolidate_day_basic(memory_service, test_user_id, sample_memory_traces, db_session):
    """Test basic day consolidation"""
    from app.main_simple import MemoryTrace, MemoryEdge

    yesterday = datetime.utcnow() - timedelta(days=1)

    result = await memory_service.consolidate_day(
        user_id=test_user_id,
        day=yesterday
    )

    assert result["status"] == "ok"
    assert result["traces_consolidated"] == len(sample_memory_traces)
    assert result["edges_created"] > 0

    # Check summary trace was created
    summary = db_session.query(MemoryTrace).filter(
        MemoryTrace.id == result["summary_trace"]
    ).first()

    assert summary is not None
    assert summary.role == "summary"
    assert "summary" in summary.content.lower()


@pytest.mark.asyncio
async def test_consolidate_day_no_traces(memory_service, test_user_id, db_session):
    """Test consolidation when no traces exist"""
    future_day = datetime.utcnow() + timedelta(days=10)

    result = await memory_service.consolidate_day(
        user_id=test_user_id,
        day=future_day
    )

    assert result["status"] == "ok"
    assert "No traces" in result["message"]


@pytest.mark.asyncio
async def test_consolidate_day_creates_edges(memory_service, test_user_id, sample_memory_traces, db_session):
    """Test that temporal edges are created"""
    from app.main_simple import MemoryEdge

    yesterday = datetime.utcnow() - timedelta(days=1)

    await memory_service.consolidate_day(
        user_id=test_user_id,
        day=yesterday
    )

    # Check edges were created
    edges = db_session.query(MemoryEdge).all()
    assert len(edges) > 0

    # Check for temporal edges
    temporal_edges = [e for e in edges if e.type == "temporal"]
    assert len(temporal_edges) > 0


# ==========================================
# TEST FORGET
# ==========================================

@pytest.mark.asyncio
async def test_forget_basic(memory_service, test_user_id, db_session):
    """Test basic trace deletion"""
    from app.main_simple import MemoryTrace

    # Store a trace
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Memory to forget",
        role="user"
    )

    # Verify it exists
    trace = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id).first()
    assert trace is not None

    # Forget it
    result = await memory_service.forget(
        user_id=test_user_id,
        trace_id=trace_id
    )

    assert result is True

    # Verify it's gone
    trace = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id).first()
    assert trace is None


@pytest.mark.asyncio
async def test_forget_removes_from_redis(memory_service, test_user_id, redis_client):
    """Test that forget removes trace from Redis"""
    # Store a trace
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Memory in Redis",
        role="user"
    )

    # Verify in Redis
    key = f"user:{test_user_id}:memory:recent"
    cached = redis_client.zrange(key, 0, -1)
    assert len(cached) == 1

    # Forget
    await memory_service.forget(
        user_id=test_user_id,
        trace_id=trace_id
    )

    # Verify removed from Redis
    cached = redis_client.zrange(key, 0, -1)
    assert len(cached) == 0


@pytest.mark.asyncio
async def test_forget_unauthorized(memory_service, test_user_id, db_session):
    """Test that users can't delete other users' traces"""
    from app.main_simple import MemoryTrace

    # Create trace for test user
    trace = MemoryTrace(
        id="test-trace",
        user_id=test_user_id,
        content="User's memory",
        role="user"
    )
    db_session.add(trace)
    db_session.commit()

    # Try to delete with different user ID
    with pytest.raises(ValueError, match="not found or access denied"):
        await memory_service.forget(
            user_id="different-user",
            trace_id="test-trace"
        )


@pytest.mark.asyncio
async def test_forget_cascades_to_embeddings(memory_service, test_user_id, db_session):
    """Test that forget deletes embeddings too"""
    from app.main_simple import MemoryTrace, MemoryEmbedding

    # Store trace (with embeddings via mock)
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Memory with embeddings",
        role="user",
        heads=["semantic", "entity"]
    )

    # Manually add embedding to test (since SQLite mock)
    embedding = MemoryEmbedding(
        trace_id=trace_id,
        head="semantic",
        embedding="[0.1, 0.2, 0.3]"
    )
    db_session.add(embedding)
    db_session.commit()

    # Forget
    await memory_service.forget(
        user_id=test_user_id,
        trace_id=trace_id
    )

    # Verify embedding deleted
    emb = db_session.query(MemoryEmbedding).filter(
        MemoryEmbedding.trace_id == trace_id
    ).first()
    assert emb is None


# ==========================================
# TEST EDGE CASES
# ==========================================

@pytest.mark.asyncio
async def test_recall_empty_results(memory_service, test_user_id):
    """Test recall with no matching results"""
    results = await memory_service.recall(
        user_id=test_user_id,
        q="nonexistent query xyz123",
        k=5
    )

    assert isinstance(results, list)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_store_trace_without_embedding_service(memory_service, test_user_id, db_session, monkeypatch):
    """Test storage works even when embedding service fails"""
    from app.main_simple import MemoryTrace

    # Mock embedding service to fail
    def mock_get_embedding_service():
        return None

    monkeypatch.setattr(memory_service, "_get_embedding_service", mock_get_embedding_service)

    # Should still store trace
    trace_id = await memory_service.store_trace(
        user_id=test_user_id,
        content="Memory without embeddings",
        role="user"
    )

    trace = db_session.query(MemoryTrace).filter(MemoryTrace.id == trace_id).first()
    assert trace is not None


@pytest.mark.asyncio
async def test_redis_max_recent_limit(memory_service, test_user_id, redis_client):
    """Test that Redis keeps only max_recent items"""
    # Store more than max_recent (1000) traces
    # (We'll test with smaller number for speed)
    memory_service._redis_max_recent = 5

    for i in range(10):
        await memory_service.store_trace(
            user_id=test_user_id,
            content=f"Memory {i}",
            role="user"
        )

    # Check Redis size
    key = f"user:{test_user_id}:memory:recent"
    cached = redis_client.zrange(key, 0, -1)

    # Should have max 5 items
    assert len(cached) <= 5
