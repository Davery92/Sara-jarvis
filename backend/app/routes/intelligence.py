"""
Intelligence feed routes — proactive AI/tech news monitoring.

Provides:
- GET  /api/intelligence/feed       — paginated feed, filterable by category/scores
- GET  /api/intelligence/digest     — latest digest
- POST /api/intelligence/{id}/dismiss  — mark item as not interesting
- POST /api/intelligence/{id}/dig-deeper — dispatch research agent
- POST /api/intelligence/scan-now   — trigger immediate scan
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intelligence", tags=["Intelligence Monitor"])


@router.get("/feed")
async def get_intelligence_feed(
    source_category: Optional[str] = Query(None, description="Filter: ai_research, local_ai, broader_tech"),
    min_novelty: float = Query(0.0, ge=0.0, le=1.0),
    min_relevance: float = Query(0.0, ge=0.0, le=1.0),
    include_dismissed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get paginated intelligence feed items."""
    conditions = []
    params = {
        "min_novelty": min_novelty,
        "min_relevance": min_relevance,
        "limit": limit,
        "offset": offset,
    }

    if not include_dismissed:
        conditions.append("dismissed = FALSE")

    if source_category:
        conditions.append("source_category = :source_category")
        params["source_category"] = source_category

    conditions.append("novelty_score >= :min_novelty")
    conditions.append("relevance_score >= :min_relevance")

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    # Get items
    rows = db.execute(text(f"""
        SELECT id, source, source_category, title, summary, url,
               novelty_score, relevance_score, discovered_at,
               included_in_digest_at, notified_at, dismissed, created_at
        FROM intelligence_item
        WHERE {where_clause}
        ORDER BY discovered_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    # Get total count
    count_row = db.execute(text(f"""
        SELECT COUNT(*) FROM intelligence_item WHERE {where_clause}
    """), params).fetchone()
    total = count_row[0] if count_row else 0

    items = []
    for row in rows:
        items.append({
            "id": row[0],
            "source": row[1],
            "source_category": row[2],
            "title": row[3],
            "summary": row[4],
            "url": row[5],
            "novelty_score": row[6],
            "relevance_score": row[7],
            "discovered_at": row[8].isoformat() if row[8] else None,
            "included_in_digest_at": row[9].isoformat() if row[9] else None,
            "notified_at": row[10].isoformat() if row[10] else None,
            "dismissed": row[11],
            "created_at": row[12].isoformat() if row[12] else None,
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/digest")
async def get_latest_digest(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the most recent intelligence digest."""
    from app.services.intelligence_monitor import intelligence_monitor
    digest = intelligence_monitor.get_latest_digest(db)
    if not digest:
        return {"digest": None, "message": "No digest available yet. Trigger a scan first."}
    return {"digest": digest}


@router.get("/stats")
async def get_intelligence_stats(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get intelligence feed statistics."""
    row = db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE discovered_at > NOW() - INTERVAL '24 hours') as last_24h,
            COUNT(*) FILTER (WHERE dismissed = TRUE) as dismissed,
            COUNT(*) FILTER (WHERE included_in_digest_at IS NOT NULL) as digested,
            AVG(novelty_score) as avg_novelty,
            AVG(relevance_score) as avg_relevance,
            COUNT(*) FILTER (WHERE source_category = 'ai_research') as ai_research_count,
            COUNT(*) FILTER (WHERE source_category = 'local_ai') as local_ai_count,
            COUNT(*) FILTER (WHERE source_category = 'broader_tech') as broader_tech_count
        FROM intelligence_item
    """)).fetchone()

    return {
        "total": row[0] if row else 0,
        "last_24h": row[1] if row else 0,
        "dismissed": row[2] if row else 0,
        "digested": row[3] if row else 0,
        "avg_novelty": round(row[4], 2) if row and row[4] else 0,
        "avg_relevance": round(row[5], 2) if row and row[5] else 0,
        "by_category": {
            "ai_research": row[6] if row else 0,
            "local_ai": row[7] if row else 0,
            "broader_tech": row[8] if row else 0,
        },
    }


@router.post("/{item_id}/dismiss")
async def dismiss_item(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an intelligence item as not interesting."""
    result = db.execute(text("""
        UPDATE intelligence_item
        SET dismissed = TRUE
        WHERE id = :item_id
        RETURNING id
    """), {"item_id": item_id}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Item not found")

    db.commit()
    return {"status": "dismissed", "id": item_id}


@router.post("/{item_id}/dig-deeper")
async def dig_deeper(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dispatch a research agent to investigate an intelligence item further."""
    row = db.execute(text("""
        SELECT title, url, summary, source_category
        FROM intelligence_item
        WHERE id = :item_id
    """), {"item_id": item_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    title, url, summary, category = row

    # Build research query
    query = f"Deep dive: {title}"
    if summary:
        query += f"\n\nContext: {summary[:300]}"
    if url:
        query += f"\n\nOriginal source: {url}"

    # Try to dispatch via learning deep research
    try:
        from app.celery_app import celery_app as app_celery

        # Create a research job in the learning system
        from app.db.session import SessionLocal
        job_db = SessionLocal()
        try:
            job_id = None
            job_row = job_db.execute(text("""
                INSERT INTO research_job (id, topic_id, query, status, created_at)
                VALUES (gen_random_uuid(), NULL, :query, 'queued', NOW())
                RETURNING id
            """), {"query": query}).fetchone()
            if job_row:
                job_id = str(job_row[0])
                job_db.commit()

                # Dispatch the research worker
                app_celery.send_task(
                    "app.tasks.learning.deep_research_worker",
                    kwargs={"job_id": job_id},
                    queue="cognitive",
                )
        finally:
            job_db.close()

        return {
            "status": "dispatched",
            "item_id": item_id,
            "research_job_id": job_id,
            "query": query[:200],
        }

    except Exception as e:
        logger.error(f"Failed to dispatch dig-deeper for {item_id}: {e}")
        return {
            "status": "error",
            "item_id": item_id,
            "error": str(e),
        }


@router.post("/scan-now")
async def trigger_scan_now(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger an immediate intelligence scan."""
    try:
        from app.celery_app import celery_app as app_celery
        result = app_celery.send_task(
            "app.tasks.intelligence.intelligence_scan",
            queue="low_priority",
        )
        return {
            "status": "dispatched",
            "task_id": result.id,
        }
    except Exception as e:
        logger.error(f"Failed to dispatch intelligence scan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger scan: {e}")
