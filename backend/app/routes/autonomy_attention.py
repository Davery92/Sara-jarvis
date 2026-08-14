"""
Autonomy attention queue routes — proactive inbox for non-urgent items.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.services.autonomy.attention_queue import attention_queue

logger = logging.getLogger(__name__)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


@router.get("/attention")
async def get_attention_items(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    exclude_categories: Optional[str] = Query(None, description="Comma-separated categories to exclude, e.g. 'system'"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get attention queue items."""
    exclude_list = [c.strip() for c in exclude_categories.split(",") if c.strip()] if exclude_categories else None
    items = await attention_queue.list_items(
        db=db, user_id=str(current_user.id),
        status=status, limit=limit, offset=offset,
        exclude_categories=exclude_list,
    )
    return {"items": items, "count": len(items)}


@router.get("/attention/count")
async def get_attention_count(
    exclude_categories: Optional[str] = Query(None, description="Comma-separated categories to exclude, e.g. 'system'"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get attention queue item counts by status."""
    exclude_list = [c.strip() for c in exclude_categories.split(",") if c.strip()] if exclude_categories else None
    counts = await attention_queue.count_by_status(
        db=db, user_id=str(current_user.id), exclude_categories=exclude_list,
    )
    unread = counts.get("new", 0) + counts.get("sent", 0)
    return {"counts": counts, "unread": unread}


@router.post("/attention/{item_id}/read")
async def mark_attention_read(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an attention item as read."""
    success = await attention_queue.mark_read(db=db, item_id=item_id, user_id=str(current_user.id))
    db.commit()
    return {"success": success}


@router.post("/attention/{item_id}/engage")
async def engage_attention_item(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an attention item as engaged (read + interacted)."""
    success = await attention_queue.mark_engaged(db=db, item_id=item_id, user_id=str(current_user.id))
    db.commit()
    return {"success": success}


@router.post("/attention/{item_id}/archive")
async def archive_attention_item(
    item_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive an attention item."""
    success = await attention_queue.mark_archived(db=db, item_id=item_id, user_id=str(current_user.id))
    db.commit()
    return {"success": success}


@router.post("/attention/{item_id}/actions/{action_id}")
async def run_attention_action(
    item_id: str,
    action_id: str,
    params: Optional[Dict[str, Any]] = Body(None),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute an action for an attention item. Optional JSON body for action params."""
    result = await attention_queue.run_action(
        db=db,
        item_id=item_id,
        action_id=action_id,
        user_id=str(current_user.id),
        params=params,
    )
    if not result.get("success"):
        error = result.get("error", "action_failed")
        status = 404 if error in ("not_found", "action_not_found") else 400
        raise HTTPException(status_code=status, detail=error)
    db.commit()
    return result


@router.post("/attention/archive-all")
async def archive_all_attention(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive all active attention items."""
    count = await attention_queue.archive_all(db=db, user_id=str(current_user.id))
    db.commit()
    return {"archived": count}


class HITLReplyRequest(BaseModel):
    message: str


@router.post("/attention/{item_id}/reply")
async def reply_to_attention_item(
    item_id: str,
    body: HITLReplyRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Reply to a human-in-the-loop ACS request.

    Pushes David's reply to Redis so the blocked ACS session can pick it up,
    then marks the attention item as completed.
    """
    user_id = str(current_user.id)

    # Fetch the attention item
    item = await attention_queue.get_item(db=db, item_id=item_id, user_id=user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Attention item not found")

    payload = item.get("payload") or {}
    if payload.get("type") != "human_input_request":
        raise HTTPException(status_code=400, detail="This item is not a human input request")

    request_id = payload.get("request_id")
    if not request_id:
        raise HTTPException(status_code=400, detail="Missing request_id in payload")

    # Push reply to Redis so the waiting session unblocks
    from app.core.redis import get_redis
    from datetime import datetime, timezone
    response_key = f"sara:acs:hitl_response:{request_id}"
    r = await get_redis()
    push_result = await r.lpush(response_key, json.dumps({
        "message": body.message,
        "replied_at": datetime.now(timezone.utc).isoformat(),
    }))
    # Set TTL so the key doesn't linger forever if session already timed out
    await r.expire(response_key, 3600)
    logger.info(
        f"HITL reply pushed: request={request_id[:8]} key={response_key} "
        f"list_len_after_push={push_result} msg={body.message[:100]}"
    )

    # Mark item completed + append action history. Use direct SQL so any failure
    # is loud (previously this went through a helper that swallowed exceptions,
    # leaving the item stuck in 'read' state with empty action_history).
    from sqlalchemy import text as _sql
    try:
        update_result = db.execute(_sql("""
            UPDATE outbox_item
            SET status = 'completed',
                completed_at = NOW(),
                updated_at   = NOW(),
                action_history = COALESCE(action_history, '[]'::jsonb) || :entry::jsonb
            WHERE id = CAST(:id AS uuid)
              AND user_id = :user_id
              AND status NOT IN ('archived', 'dropped', 'completed')
        """), {
            "id": item_id,
            "user_id": user_id,
            "entry": json.dumps({
                "action_id": "reply",
                "kind": "hitl_reply",
                "summary": f"David replied: {body.message[:100]}",
                "at": datetime.now(timezone.utc).isoformat(),
            }),
        })
        rowcount = update_result.rowcount if hasattr(update_result, "rowcount") else None
        db.commit()
        logger.info(
            f"HITL reply for request {request_id[:8]}: item={item_id[:8]} "
            f"rows_updated={rowcount} msg={body.message[:100]}"
        )
        if rowcount == 0:
            logger.warning(
                f"HITL reply: item {item_id[:8]} was NOT updated (rowcount=0). "
                f"Status may already be terminal."
            )
    except Exception as exc:
        db.rollback()
        logger.error(
            f"HITL reply: failed to mark item {item_id[:8]} completed: {exc}",
            exc_info=True,
        )
        # Don't fail the request — the Redis push already succeeded, so Sara
        # will still unblock. Just warn in the response.
        return {
            "success": True,
            "request_id": request_id,
            "message": "Reply sent to Sara, but item status update failed",
            "warning": str(exc)[:200],
        }

    return {
        "success": True,
        "request_id": request_id,
        "message": "Reply sent to Sara",
    }
