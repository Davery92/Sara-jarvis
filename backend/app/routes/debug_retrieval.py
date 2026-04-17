"""Debug endpoint for retrieval pipeline observability.

Shows the funnel: which retrieval sources fired, what came back, how long
they took, and which ran degraded. Pairs with /debug/notification-funnel
for a full view of how context ends up in Sara's working memory.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User
from app.services import retrieval_observer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/debug/retrieval-funnel")
async def retrieval_funnel(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
):
    """Retrieval pipeline funnel.

    Returns per-source cumulative aggregates plus the most recent N events
    from the in-memory ring buffer. Also includes BGE reranker fallback
    stats so you can tell when ranking is running degraded.
    """
    snap = retrieval_observer.snapshot(limit=limit)

    # BGE reranker cumulative stats — surfaced here since reranking is
    # part of the same funnel even though it lives in its own module.
    try:
        from app.services.bge_reranker import BGEReranker
        snap["reranker"] = BGEReranker.get_stats()
    except Exception as exc:  # pragma: no cover
        snap["reranker"] = {"error": f"stats_unavailable: {exc.__class__.__name__}"}

    return snap
