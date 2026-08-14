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

    # Silent-failure trackers (PKG, observation_log, deliberation_gate, etc.).
    # Lets us see when fire-and-forget subsystems are degraded without having
    # to tail logs waiting for the rate-limited WARNING to fire.
    try:
        from app.services.silent_failure_tracker import Tracker
        snap["silent_failures"] = Tracker.all_stats()
    except Exception as exc:  # pragma: no cover
        snap["silent_failures"] = {"error": f"stats_unavailable: {exc.__class__.__name__}"}

    # Memory health — embedding gap counts for episodes and PKG. A spike in
    # gaps means the embedding service has been silently failing and
    # retrieval is about to look dumber than it should.
    try:
        from app.services.personal_knowledge_graph import get_memory_health
        snap["memory_health"] = get_memory_health()
    except Exception as exc:
        snap["memory_health"] = {"error": f"health_check_failed:{exc.__class__.__name__}"}

    return snap


@router.get("/debug/swallow-counts")
async def swallow_counts(
    days: int = 7,
    current_user: User = Depends(get_current_user),
):
    """Silent-failure counts by call site (app.core.swallow.swallow()),
    last `days` days.

    Redis-backed and daily-bucketed, so counts survive a container restart
    and aggregate across the backend + Celery workers — the early-warning
    this system otherwise only gets from manual audits, months late.
    """
    from datetime import datetime, timedelta, timezone

    from app.core.redis import get_redis
    from app.core.swallow import _KEY_PREFIX

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    sites: dict = {}
    try:
        r = await get_redis()
        cursor = 0
        pattern = f"{_KEY_PREFIX}:*"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=pattern, count=200)
            for key in keys:
                try:
                    _, site, date = key.rsplit(":", 2)
                except ValueError:
                    continue
                if date < cutoff:
                    continue
                count = int(await r.get(key) or 0)
                entry = sites.setdefault(site, {"total": 0, "by_day": {}})
                entry["total"] += count
                entry["by_day"][date] = count
            if cursor == 0:
                break
    except Exception as exc:
        return {"error": f"redis_unavailable:{exc.__class__.__name__}", "sites": {}}

    ranked = dict(sorted(sites.items(), key=lambda kv: -kv[1]["total"]))
    return {"window_days": days, "sites": ranked}
