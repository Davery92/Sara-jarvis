"""
Autonomy attention queue routes — proactive inbox for non-urgent items.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.services.autonomy.attention_queue import attention_queue

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


@router.get("/attention")
async def get_attention_items(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get attention queue items."""
    items = await attention_queue.list_items(
        db=db, user_id=str(current_user.id),
        status=status, limit=limit, offset=offset,
    )
    return {"items": items, "count": len(items)}


@router.get("/attention/count")
async def get_attention_count(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get attention queue item counts by status."""
    counts = await attention_queue.count_by_status(db=db, user_id=str(current_user.id))
    unread = counts.get("new", 0) + counts.get("sent", 0)
    return {"counts": counts, "unread": unread}


@router.post("/attention/{item_id}/read")
async def mark_attention_read(
    item_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an attention item as read."""
    success = await attention_queue.mark_read(db=db, item_id=item_id, user_id=str(current_user.id))
    await db.commit()
    return {"success": success}


@router.post("/attention/{item_id}/archive")
async def archive_attention_item(
    item_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive an attention item."""
    success = await attention_queue.mark_archived(db=db, item_id=item_id, user_id=str(current_user.id))
    await db.commit()
    return {"success": success}


@router.post("/attention/archive-all")
async def archive_all_attention(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive all active attention items."""
    count = await attention_queue.archive_all(db=db, user_id=str(current_user.id))
    await db.commit()
    return {"archived": count}
