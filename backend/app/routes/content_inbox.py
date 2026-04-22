"""Content Inbox routes — share URLs, files, and text to Sara."""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.shared_content import SharedContent
from app.schemas.content_inbox import (
    ShareURLRequest,
    ShareTextRequest,
    SharedContentSummary,
    SharedContentDetail,
    StatusUpdate,
    InboxStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbox", tags=["Content Inbox"])


@router.post("/share", response_model=SharedContentSummary)
async def share_url_or_text(
    request: ShareURLRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Share a URL to the inbox. Content will be extracted asynchronously."""
    from app.services.content_inbox_service import content_inbox_service

    item = await content_inbox_service.share_url(
        db=db, user_id=current_user.id, url=request.url, title=request.title
    )
    return SharedContentSummary.model_validate(item)


@router.post("/share/text", response_model=SharedContentSummary)
async def share_text(
    request: ShareTextRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Share plain text to the inbox."""
    from app.services.content_inbox_service import content_inbox_service

    item = await content_inbox_service.share_text(
        db=db, user_id=current_user.id, text_content=request.text, title=request.title
    )
    return SharedContentSummary.model_validate(item)


@router.post("/upload", response_model=SharedContentSummary)
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Share a file (PDF, DOCX, TXT, etc.) to the inbox."""
    from app.services.content_inbox_service import content_inbox_service

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    item = await content_inbox_service.share_file(
        db=db,
        user_id=current_user.id,
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
    )
    return SharedContentSummary.model_validate(item)


@router.get("", response_model=list[SharedContentSummary])
async def list_inbox(
    status: Optional[str] = Query(None, description="Filter by status: unread, read, kept, discarded"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List inbox items with optional status filter."""
    q = db.query(SharedContent).filter(SharedContent.user_id == current_user.id)
    if status:
        q = q.filter(SharedContent.status == status)
    items = q.order_by(SharedContent.shared_at.desc()).offset(offset).limit(limit).all()
    return [SharedContentSummary.model_validate(item) for item in items]


@router.get("/stats", response_model=InboxStats)
async def inbox_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get inbox item counts by status."""
    rows = (
        db.query(SharedContent.status, func.count(SharedContent.id))
        .filter(SharedContent.user_id == current_user.id)
        .group_by(SharedContent.status)
        .all()
    )
    counts = {row[0]: row[1] for row in rows}
    return InboxStats(
        unread=counts.get("unread", 0),
        read=counts.get("read", 0),
        kept=counts.get("kept", 0),
        total=sum(counts.values()),
    )


@router.post("/mark-all-read")
async def mark_all_inbox_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all unread inbox items as read."""
    now = datetime.now(timezone.utc)
    updated = (
        db.query(SharedContent)
        .filter(
            SharedContent.user_id == current_user.id,
            SharedContent.status == "unread",
        )
        .update(
            {
                SharedContent.status: "read",
                SharedContent.read_at: now,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return {"success": True, "updated": updated}


@router.get("/search")
async def search_inbox(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Semantic search across inbox items."""
    from app.services.content_inbox_service import content_inbox_service

    results = await content_inbox_service.search_inbox(
        db=db, user_id=current_user.id, query=q, limit=limit
    )
    return results


@router.get("/{item_id}", response_model=SharedContentDetail)
async def get_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full item detail. Marks item as read if currently unread."""
    item = db.query(SharedContent).filter(
        SharedContent.id == item_id,
        SharedContent.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Auto-mark as read
    if item.status == "unread":
        item.status = "read"
        item.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)

    return SharedContentDetail.model_validate(item)


@router.get("/{item_id}/file")
async def get_item_file(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve the original file from MinIO for native viewing."""
    item = db.query(SharedContent).filter(
        SharedContent.id == item_id,
        SharedContent.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not item.storage_key:
        raise HTTPException(status_code=404, detail="No file associated with this item")

    try:
        from app.services.docs_ingest import DocumentProcessor
        processor = DocumentProcessor()
        file_bytes = processor.get_file(item.storage_key)
    except Exception as e:
        logger.error(f"Failed to retrieve file from MinIO: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

    media_type = item.mime_type or "application/octet-stream"
    filename = item.original_filename or item.storage_key
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.patch("/{item_id}/status", response_model=SharedContentSummary)
async def update_status(
    item_id: str,
    body: StatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Keep or discard an inbox item."""
    if body.status not in ("kept", "discarded"):
        raise HTTPException(status_code=400, detail="Status must be 'kept' or 'discarded'")

    item = db.query(SharedContent).filter(
        SharedContent.id == item_id,
        SharedContent.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.status = body.status
    item.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return SharedContentSummary.model_validate(item)


@router.delete("/{item_id}")
async def delete_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard delete an inbox item (+ MinIO cleanup)."""
    item = db.query(SharedContent).filter(
        SharedContent.id == item_id,
        SharedContent.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Clean up MinIO file if present
    if item.storage_key:
        try:
            from app.services.docs_ingest import DocumentProcessor
            processor = DocumentProcessor()
            processor.delete_file(item.storage_key)
        except Exception as e:
            logger.warning(f"Failed to delete file from MinIO: {e}")

    db.delete(item)
    db.commit()
    return {"message": "Deleted", "id": item_id}
