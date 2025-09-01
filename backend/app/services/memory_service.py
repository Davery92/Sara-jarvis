from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta


class MemoryService:
    """
    Skeleton for human-like memory service.
    - Write traces to Postgres (memory_trace + memory_embedding per head)
    - Read via Redis working set, then Postgres HNSW, then graph edges
    """

    def __init__(self, redis_client=None, db_session_factory=None):
        self.redis = redis_client
        self.SessionLocal = db_session_factory

    async def store_trace(self, user_id: str, content: str, role: str = "assistant",
                          heads: Optional[List[str]] = None, salience: Optional[float] = None,
                          source: Optional[Dict[str, Any]] = None, meta: Optional[Dict[str, Any]] = None) -> str:
        """Store a trace and optional embeddings (heads). Returns trace_id."""
        # TODO: implement with SQLAlchemy models/migrations
        raise NotImplementedError

    async def recall(self, user_id: str, q: str, k: int = 10, heads: Optional[List[str]] = None,
                     time_window: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recall top-k traces using Redis working set → Postgres HNSW → edges. Returns scored traces."""
        # TODO: implement retrieval pipeline
        raise NotImplementedError

    async def consolidate_day(self, day: Optional[datetime] = None) -> Dict[str, Any]:
        """Summarize previous day, extract edges, and downshift old traces."""
        # TODO: implement consolidation
        raise NotImplementedError

    async def forget(self, trace_id: str) -> bool:
        """Hard delete trace + embeddings + edges."""
        # TODO: implement deletion with cascading clean-up
        raise NotImplementedError

