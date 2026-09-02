"""MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 6: memory_service.search_memory
ranking regression tests. Runs against the real Postgres+pgvector instance —
seeds a few throwaway episodes at controlled cosine similarities to a nonce
query (so nothing in the real corpus can outrank them), exercises the actual
composite-score SQL, and cleans up by exact id afterward.

Before the fix: sim*0.55 + importance*0.25 + freq*0.10 + rating*0.05 +
exploration*0.05, no recency term, no floor — an old, much-accessed,
high-importance episode could structurally outrank a fresher, more similar
one. After: sim*0.70 + recency*0.15 + importance*0.10 + rating*0.05, no
access_count term, plus a 0.45 similarity floor.
"""
import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db.base import SessionLocal
from app.core.config import get_owner_id
from app.services.memory_service import MemoryService
from app.services.memory_scoring import MIN_SIMILARITY_FLOOR


def _unit(v: list) -> list:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def _rotate(base: list, ortho: list, cos_theta: float) -> list:
    """Unit vector at cosine similarity `cos_theta` to `base` (base/ortho
    must be unit vectors, mutually orthogonal)."""
    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
    return [cos_theta * b + sin_theta * o for b, o in zip(base, ortho)]


@pytest.fixture
async def seeded_episodes():
    # Use the exact embedding path search_memory itself calls internally
    # (MemoryService._get_embedding_service -> app.services.embeddings.get_embedding)
    # so the synthetic vectors below are built relative to the same query
    # embedding the search will actually use.
    from app.services.embeddings import get_embedding

    # A nonce query — no real episode should have meaningful cosine
    # similarity to it, so our controlled synthetic vectors dominate the
    # ranking regardless of what else is in the real corpus.
    query = f"zqx-nonce-probe-{uuid.uuid4().hex[:12]}"
    try:
        query_vec = await get_embedding(query)
    except Exception:
        query_vec = None
    if not query_vec:
        pytest.skip("embedding service unavailable")

    dim = len(query_vec)
    base = _unit(query_vec)
    seed = [0.0] * dim
    seed[0 if abs(base[0]) < 0.9 else 1] = 1.0
    dot = sum(a * b for a, b in zip(seed, base))
    ortho = _unit([s - dot * b for s, b in zip(seed, base)])

    user_id = get_owner_id()
    fresh_id, old_id, below_floor_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    ids = [fresh_id, old_id, below_floor_id]

    # fresh: moderate similarity, low importance, no access history
    fresh_vec = _rotate(base, ortho, 0.60)
    # old: slightly LOWER similarity but maxed-out importance/access — the
    # exact shape that gamed the old formula
    old_vec = _rotate(base, ortho, 0.55)
    # comfortably under the 0.45 floor
    below_floor_vec = _rotate(base, ortho, 0.20)

    now = datetime.now(timezone.utc)
    old_created = now - timedelta(days=60)

    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO episode
              (id, user_id, role, content, importance, access_count, created_at, embedding, source)
            VALUES
              (:fresh_id, :uid, 'user', 'PHASE6_TEST fresh high-similarity episode',
               0.5, 0, :now, CAST(:fresh_vec AS vector), 'test'),
              (:old_id, :uid, 'user', 'PHASE6_TEST old lower-similarity high-importance/access episode',
               1.0, 1000, :old_created, CAST(:old_vec AS vector), 'test'),
              (:bf_id, :uid, 'user', 'PHASE6_TEST below-floor episode',
               0.5, 0, :now, CAST(:bf_vec AS vector), 'test')
        """), {
            "fresh_id": fresh_id, "old_id": old_id, "bf_id": below_floor_id,
            "uid": user_id, "now": now, "old_created": old_created,
            "fresh_vec": str(fresh_vec), "old_vec": str(old_vec), "bf_vec": str(below_floor_vec),
        })
        db.commit()
        yield {
            "user_id": user_id, "query": query,
            "fresh_id": fresh_id, "old_id": old_id, "below_floor_id": below_floor_id,
        }
    finally:
        db.execute(text("DELETE FROM episode WHERE id = ANY(:ids)"), {"ids": ids})
        db.commit()
        db.close()


class TestSearchMemoryRanking:
    @pytest.mark.asyncio
    async def test_fresh_high_sim_outranks_old_high_importance(self, seeded_episodes):
        svc = MemoryService(db_session_factory=SessionLocal)
        results = await svc.search_memory(
            seeded_episodes["user_id"], seeded_episodes["query"], scopes=["episodes"], limit=10,
        )
        ranked_ids = [r["episode_id"] for r in results]

        assert seeded_episodes["fresh_id"] in ranked_ids, "fresh episode missing from top 10"
        assert seeded_episodes["old_id"] in ranked_ids, "old episode missing from top 10"
        assert ranked_ids.index(seeded_episodes["fresh_id"]) < ranked_ids.index(seeded_episodes["old_id"]), (
            "fresh, more-similar episode should outrank the old high-importance/"
            "high-access one — access_count must not be able to buy back a rank"
        )

    @pytest.mark.asyncio
    async def test_below_floor_excluded(self, seeded_episodes):
        svc = MemoryService(db_session_factory=SessionLocal)
        results = await svc.search_memory(
            seeded_episodes["user_id"], seeded_episodes["query"], scopes=["episodes"], limit=10,
        )
        ranked_ids = [r["episode_id"] for r in results]
        assert seeded_episodes["below_floor_id"] not in ranked_ids

    @pytest.mark.asyncio
    async def test_returned_similarity_respects_floor_constant(self, seeded_episodes):
        svc = MemoryService(db_session_factory=SessionLocal)
        results = await svc.search_memory(
            seeded_episodes["user_id"], seeded_episodes["query"], scopes=["episodes"], limit=10,
        )
        assert all(r["similarity"] >= MIN_SIMILARITY_FLOOR for r in results)
