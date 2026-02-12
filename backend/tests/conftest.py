"""
Pytest Configuration and Fixtures

Provides test fixtures for:
- Database sessions (in-memory SQLite)
- Redis client (fakeredis)
- Mock LLM client
- Mock embedding service
- Test user authentication
- Activity state machine
- Interruptibility / notification queue
- Intent classifier / context router
"""

import pytest
import asyncio
from datetime import datetime, timezone
from typing import Generator, AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import fakeredis
from unittest.mock import AsyncMock, MagicMock
import uuid

# Import models and database setup
from app.main_simple import Base

# Import services for test fixtures
from app.services.activity_state_machine import (
    ActivityStateMachine, ActivityState, ActivitySnapshot, ActivitySignal,
)
from app.services.interruptibility import NotificationQueue
from app.services.intent_classifier import ToolIntentClassifier
from app.services.context_router import ContextRouter
from app.services.unified_context import UnifiedContextSnapshot


# ==========================================
# EVENT LOOP FIXTURE
# ==========================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ==========================================
# DATABASE FIXTURES
# ==========================================

@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite database engine for testing.

    Note: Does NOT create all tables automatically because some models
    use PostgreSQL-specific types (JSONB) that aren't compatible with SQLite.
    Tests should create only the tables they need using their own setup fixtures.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Don't create all tables - some have JSONB columns that SQLite doesn't support
    # Each test should create only the tables it needs using its own setup fixture
    # Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create a new database session for each test"""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def db_session_factory(db_engine):
    """Provide a session factory for services that create their own sessions"""
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


# ==========================================
# REDIS FIXTURES
# ==========================================

@pytest.fixture(scope="function")
def redis_client():
    """Create a fake Redis client for testing"""
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    yield fake_redis
    fake_redis.flushall()


# ==========================================
# MOCK SERVICE FIXTURES
# ==========================================

@pytest.fixture
def mock_embedding_service():
    """Mock embedding service that returns dummy embeddings"""
    async def get_embedding(text: str):
        # Return a dummy 1024-dimensional embedding
        # Use hash of text for reproducibility
        import hashlib
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        # Generate pseudo-random but deterministic embedding
        embedding = [(hash_val + i) % 100 / 100.0 for i in range(1024)]
        return embedding

    return get_embedding


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing"""
    mock = AsyncMock()

    async def chat_completion(messages, temperature=0.7, max_tokens=None):
        # Return a mock JSON response for dream consolidation
        import json
        return json.dumps({
            "summary": "Test summary of the cluster",
            "key_points": ["point 1", "point 2", "point 3"],
            "emotional_tone": "neutral",
            "topics": ["test", "mock", "data"]
        })

    mock.chat_completion = chat_completion
    return mock


# ==========================================
# TEST USER FIXTURES
# ==========================================

@pytest.fixture
def test_user_id() -> str:
    """Generate a unique test user ID"""
    return str(uuid.uuid4())


@pytest.fixture
def test_user(db_session, test_user_id):
    """Create a test user in the database"""
    from app.main_simple import User
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    user = User(
        id=test_user_id,
        email="test@example.com",
        hashed_password=pwd_context.hash("testpassword"),
        full_name="Test User"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ==========================================
# MEMORY SERVICE FIXTURES
# ==========================================

@pytest.fixture
def memory_service(redis_client, db_session_factory, mock_embedding_service, memory_tables, monkeypatch):
    """Create a MemoryService instance with mocked dependencies"""
    from app.services.memory_service import MemoryService

    # Force SQLite-compatible embedding storage (JSON-serialized, not raw pgvector)
    monkeypatch.setattr("app.main_simple.PGVECTOR_AVAILABLE", False)
    monkeypatch.setattr("app.main_simple.DATABASE_URL", "sqlite:///:memory:")

    service = MemoryService(redis_client, db_session_factory)

    # Mock the embedding service
    def mock_get_embedding_service():
        return mock_embedding_service

    monkeypatch.setattr(service, "_get_embedding_service", mock_get_embedding_service)

    return service


# ==========================================
# DREAM CONSOLIDATION FIXTURES
# ==========================================

@pytest.fixture
def dream_service(mock_llm_client, mock_embedding_service, monkeypatch):
    """Create a DreamConsolidationService with mocked dependencies"""
    from app.services.dream_consolidation import DreamConsolidationService

    # Force SQLite-compatible embedding storage
    monkeypatch.setattr("app.main_simple.PGVECTOR_AVAILABLE", False)
    monkeypatch.setattr("app.main_simple.DATABASE_URL", "sqlite:///:memory:")

    service = DreamConsolidationService()

    # Mock LLM client
    def mock_get_llm():
        return mock_llm_client

    # Mock embedding service
    def mock_get_embedding():
        return mock_embedding_service

    monkeypatch.setattr(service, "_get_llm_client", mock_get_llm)
    monkeypatch.setattr(service, "_get_embedding_service", mock_get_embedding)

    return service


# ==========================================
# MEMORY TABLE FIXTURES
# ==========================================

@pytest.fixture
def memory_tables(db_engine):
    """Create memory-related tables in SQLite for tests.

    Creates memory_trace, memory_embedding, memory_edge, and dream_insight
    using SQLite-compatible types (TEXT instead of JSONB, TEXT for vectors).
    """
    from sqlalchemy import text

    with db_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_trace (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                role TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                salience REAL,
                source TEXT,
                meta TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_embedding (
                trace_id TEXT NOT NULL,
                head TEXT NOT NULL,
                embedding TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trace_id, head)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_edge (
                src TEXT NOT NULL,
                dst TEXT NOT NULL,
                type TEXT NOT NULL,
                weight REAL,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (src, dst, type)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dream_insight (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                dream_date TIMESTAMP,
                insight_type TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                title TEXT NOT NULL,
                content TEXT,
                related_episodes TEXT,
                embedding TEXT,
                surfaced_at TIMESTAMP,
                user_feedback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()


# ==========================================
# SAMPLE DATA FIXTURES
# ==========================================

@pytest.fixture
def sample_memory_traces(db_session, test_user_id, memory_tables):
    """Create sample memory traces for testing"""
    from app.main_simple import MemoryTrace
    from datetime import datetime, timedelta

    traces = []
    base_time = datetime.utcnow() - timedelta(days=1)

    for i in range(5):
        trace = MemoryTrace(
            id=str(uuid.uuid4()),
            user_id=test_user_id,
            content=f"Test memory trace {i}: This is sample content about topic {i % 3}",
            role="user" if i % 2 == 0 else "assistant",
            salience=0.5 + (i * 0.1),
            created_at=base_time + timedelta(minutes=i * 10)
        )
        db_session.add(trace)
        traces.append(trace)

    db_session.commit()
    return traces


# ==========================================
# HELPER FUNCTIONS
# ==========================================

@pytest.fixture
def assert_similar_embeddings():
    """Helper to assert two embeddings are similar (cosine similarity)"""
    import numpy as np

    def _assert_similar(emb1, emb2, threshold=0.8):
        v1 = np.array(emb1)
        v2 = np.array(emb2)
        similarity = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        assert similarity >= threshold, f"Embeddings not similar enough: {similarity} < {threshold}"

    return _assert_similar


# ==========================================
# ACTIVITY STATE MACHINE FIXTURES
# ==========================================

@pytest.fixture
def activity_machine():
    """Fresh ActivityStateMachine per test (avoid singleton bleed)."""
    return ActivityStateMachine()


@pytest.fixture
def make_snapshot():
    """Factory for ActivitySnapshot instances."""
    def _make(state=ActivityState.ACTIVE, confidence=0.8, room="living_room",
              interruptibility=None):
        if interruptibility is None:
            from app.services.activity_state_machine import STATE_INTERRUPTIBILITY
            interruptibility = STATE_INTERRUPTIBILITY.get(state, 0.5)
        return ActivitySnapshot(
            state=state,
            confidence=confidence,
            since=datetime.now(timezone.utc),
            reason="test",
            room=room,
            interruptibility=interruptibility,
            signals=[],
        )
    return _make


@pytest.fixture
def make_signal():
    """Factory for ActivitySignal instances."""
    from zoneinfo import ZoneInfo
    def _make(signal_type="motion", source="binary_sensor.office_motion",
              value="on", metadata=None, hour=None):
        ts = datetime.now(ZoneInfo("America/New_York"))
        if hour is not None:
            ts = ts.replace(hour=hour, minute=0, second=0)
        return ActivitySignal(
            signal_type=signal_type,
            source=source,
            value=value,
            timestamp=ts,
            metadata=metadata or {},
        )
    return _make


# ==========================================
# NOTIFICATION QUEUE FIXTURES
# ==========================================

@pytest.fixture
def notification_queue():
    """Fresh NotificationQueue per test."""
    q = NotificationQueue()
    q.clear()
    return q


# ==========================================
# CLASSIFIER / ROUTER FIXTURES
# ==========================================

@pytest.fixture
def tool_classifier():
    """Fresh ToolIntentClassifier per test."""
    return ToolIntentClassifier()


@pytest.fixture
def context_router():
    """Fresh ContextRouter per test."""
    return ContextRouter()


# ==========================================
# UNIFIED CONTEXT SNAPSHOT FIXTURE
# ==========================================

@pytest.fixture
def make_snapshot_ctx():
    """Factory for UnifiedContextSnapshot with sensible defaults."""
    def _make(**overrides):
        defaults = dict(
            activity_state="ACTIVE",
            activity_confidence=0.7,
            interruptibility=0.8,
            hours_since_last_chat=3.0,
            has_chatted_today=True,
            is_past_bedtime=False,
            alertness=0.6,
            stress_load=0.3,
            learning_reviews_due=0,
        )
        defaults.update(overrides)
        return UnifiedContextSnapshot(**defaults)
    return _make


# ==========================================
# MOCK BACKGROUND LLM FIXTURE
# ==========================================

@pytest.fixture
def mock_background_llm():
    """Mock background LLM client that returns structured JSON."""
    async def _mock_chat(messages, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": "Quiet evening. David hasn't chatted in a while."
                }
            }]
        }
    mock = AsyncMock()
    mock.chat_completion = AsyncMock(side_effect=_mock_chat)
    return mock
