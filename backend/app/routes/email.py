"""Email management routes for Microsoft Graph integration."""
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from io import BytesIO

from app.db.session import get_db
from app.models.user import User
from app.models.email import Email, EmailAttachment, EmailSyncState
from app.schemas.email import (
    EmailResponse,
    EmailDetailResponse,
    EmailListResponse,
    EmailAttachmentResponse,
    EmailStatsResponse,
    EmailChatRequest,
    EmailChatResponse,
    MarkReadRequest
)
from app.core.deps import get_current_user
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["Email"])


@router.get("", response_model=EmailListResponse)
async def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mailbox: Optional[str] = None,
    category: Optional[str] = None,
    unread_only: bool = False,
    action_required_only: bool = False,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List emails with filtering and pagination.

    Filters:
    - mailbox: Filter by specific mailbox
    - category: Filter by Sara's category (support, urgent, etc.)
    - unread_only: Only show unread emails
    - action_required_only: Only show emails needing action
    - search: Search in subject and body
    """
    query = db.query(Email).filter(Email.user_id == current_user.id)

    # Apply filters
    if mailbox:
        query = query.filter(Email.mailbox == mailbox)

    if category:
        query = query.filter(Email.category == category)

    if unread_only:
        query = query.filter(Email.is_read == False)

    if action_required_only:
        query = query.filter(Email.action_required == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Email.subject.ilike(search_term)) |
            (Email.body_preview.ilike(search_term)) |
            (Email.sender_name.ilike(search_term)) |
            (Email.sender_email.ilike(search_term))
        )

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    emails = query.order_by(desc(Email.received_at)).offset(offset).limit(page_size).all()

    # Build response
    email_responses = []
    for email in emails:
        attachment_count = db.query(func.count(EmailAttachment.id)).filter(
            EmailAttachment.email_id == email.id
        ).scalar() or 0

        email_responses.append(EmailResponse(
            id=email.id,
            mailbox=email.mailbox,
            subject=email.subject,
            sender_email=email.sender_email,
            sender_name=email.sender_name,
            received_at=email.received_at.isoformat() if email.received_at else "",
            importance=email.importance or "normal",
            is_read=email.is_read or False,
            body_preview=email.body_preview,
            has_attachments=attachment_count > 0,
            attachment_count=attachment_count,
            category=email.category,
            importance_score=email.importance_score,
            summary=email.summary,
            action_required=email.action_required or False,
            to_recipients=email.to_recipients or [],
            cc_recipients=email.cc_recipients or []
        ))

    return EmailListResponse(
        emails=email_responses,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(emails)) < total
    )


@router.get("/stats", response_model=EmailStatsResponse)
async def get_email_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get email dashboard statistics."""
    base_query = db.query(Email).filter(Email.user_id == current_user.id)

    # Total and unread counts
    total_emails = base_query.count()
    unread_count = base_query.filter(Email.is_read == False).count()

    # By category
    category_counts = db.query(
        Email.category,
        func.count(Email.id)
    ).filter(
        Email.user_id == current_user.id,
        Email.category.isnot(None)
    ).group_by(Email.category).all()
    by_category = {cat: count for cat, count in category_counts if cat}

    # By mailbox
    mailbox_counts = db.query(
        Email.mailbox,
        func.count(Email.id)
    ).filter(Email.user_id == current_user.id).group_by(Email.mailbox).all()
    by_mailbox = {mailbox: count for mailbox, count in mailbox_counts}

    # Action required
    action_required_count = base_query.filter(Email.action_required == True).count()

    # High importance
    high_importance_count = base_query.filter(Email.importance_score >= 0.8).count()

    # Last sync
    last_sync = db.query(func.max(EmailSyncState.last_sync_at)).filter(
        EmailSyncState.user_id == current_user.id
    ).scalar()

    return EmailStatsResponse(
        total_emails=total_emails,
        unread_count=unread_count,
        by_category=by_category,
        by_mailbox=by_mailbox,
        action_required_count=action_required_count,
        high_importance_count=high_importance_count,
        last_sync=last_sync.isoformat() if last_sync else None
    )


@router.get("/{email_id}", response_model=EmailDetailResponse)
async def get_email(
    email_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get full email detail by ID."""
    email = db.query(Email).filter(
        Email.id == email_id,
        Email.user_id == current_user.id
    ).first()

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Get attachments
    attachments = db.query(EmailAttachment).filter(
        EmailAttachment.email_id == email_id
    ).all()

    attachment_responses = [
        EmailAttachmentResponse(
            id=att.id,
            filename=att.filename,
            content_type=att.content_type,
            size=att.size or 0,
            is_inline=att.is_inline or False,
            is_riskninja_relevant=att.is_riskninja_relevant or False,
            has_download=att.minio_key is not None
        )
        for att in attachments
    ]

    return EmailDetailResponse(
        id=email.id,
        mailbox=email.mailbox,
        subject=email.subject,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        received_at=email.received_at.isoformat() if email.received_at else "",
        importance=email.importance or "normal",
        is_read=email.is_read or False,
        body_preview=email.body_preview,
        body_text=email.body_text,
        body_html=email.body_html,
        has_attachments=len(attachments) > 0,
        attachment_count=len(attachments),
        category=email.category,
        importance_score=email.importance_score,
        summary=email.summary,
        action_required=email.action_required or False,
        to_recipients=email.to_recipients or [],
        cc_recipients=email.cc_recipients or [],
        conversation_id=email.conversation_id,
        internet_message_id=email.internet_message_id,
        attachments=attachment_responses,
        analyzed_at=email.analyzed_at.isoformat() if email.analyzed_at else None,
        synced_at=email.synced_at.isoformat() if email.synced_at else ""
    )


@router.get("/{email_id}/attachments")
async def list_attachments(
    email_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List attachments for an email."""
    # Verify email ownership
    email = db.query(Email).filter(
        Email.id == email_id,
        Email.user_id == current_user.id
    ).first()

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    attachments = db.query(EmailAttachment).filter(
        EmailAttachment.email_id == email_id
    ).all()

    return [
        EmailAttachmentResponse(
            id=att.id,
            filename=att.filename,
            content_type=att.content_type,
            size=att.size or 0,
            is_inline=att.is_inline or False,
            is_riskninja_relevant=att.is_riskninja_relevant or False,
            has_download=att.minio_key is not None
        )
        for att in attachments
    ]


@router.get("/{email_id}/attachments/{attachment_id}/download")
async def download_attachment(
    email_id: str,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download an attachment from MinIO."""
    # Verify email ownership
    email = db.query(Email).filter(
        Email.id == email_id,
        Email.user_id == current_user.id
    ).first()

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Get attachment
    attachment = db.query(EmailAttachment).filter(
        EmailAttachment.id == attachment_id,
        EmailAttachment.email_id == email_id
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if not attachment.minio_key:
        # Try to download from Graph API if not yet in MinIO
        from app.tasks.email_sync import download_attachments
        download_attachments.delay(email_id, email.mailbox)
        raise HTTPException(
            status_code=202,
            detail="Attachment download queued. Please try again in a moment."
        )

    try:
        from minio import Minio

        minio_url = settings.minio_url.replace("http://", "").replace("https://", "")
        minio_client = Minio(
            minio_url,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False
        )

        # Get object from MinIO
        response = minio_client.get_object(attachment.minio_bucket, attachment.minio_key)
        content = response.read()
        response.close()
        response.release_conn()

        return StreamingResponse(
            BytesIO(content),
            media_type=attachment.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{attachment.filename}"',
                "Content-Length": str(len(content))
            }
        )

    except Exception as e:
        logger.error(f"Failed to download attachment: {e}")
        raise HTTPException(status_code=500, detail="Failed to download attachment")


@router.post("/{email_id}/mark-read")
async def mark_email_read(
    email_id: str,
    request: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark an email as read/unread."""
    email = db.query(Email).filter(
        Email.id == email_id,
        Email.user_id == current_user.id
    ).first()

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    email.is_read = request.is_read
    db.commit()

    # Also mark as read in Graph API
    try:
        from app.services.msgraph_service import get_msgraph_service
        import asyncio

        msgraph = get_msgraph_service()
        asyncio.create_task(msgraph.mark_as_read(email.mailbox, email_id, request.is_read))
    except Exception as e:
        logger.warning(f"Failed to sync read status to Graph: {e}")

    return {"status": "ok", "is_read": email.is_read}


@router.post("/{email_id}/chat", response_model=EmailChatResponse)
async def chat_about_email(
    email_id: str,
    request: EmailChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Chat with Sara about a specific email.
    Includes email content and related context.
    """
    import httpx

    email = db.query(Email).filter(
        Email.id == email_id,
        Email.user_id == current_user.id
    ).first()

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Get attachments for context
    attachments = db.query(EmailAttachment).filter(
        EmailAttachment.email_id == email_id
    ).all()

    # Build email context
    attachment_list = "\n".join([
        f"  - {att.filename} ({att.content_type}, {att.size} bytes)"
        + (" [RiskNinja relevant]" if att.is_riskninja_relevant else "")
        for att in attachments
    ]) if attachments else "  (none)"

    email_context = f"""
EMAIL CONTEXT:
Subject: {email.subject}
From: {email.sender_name} <{email.sender_email}>
Received: {email.received_at}
Mailbox: {email.mailbox}

Attachments:
{attachment_list}

Sara's Analysis:
- Category: {email.category or 'Not analyzed'}
- Importance: {email.importance_score or 'Not scored'}
- Summary: {email.summary or 'No summary'}
- Action Required: {email.action_required}

Email Content:
{email.body_text[:4000] if email.body_text else email.body_preview}
"""

    # Get related emails from same sender for context
    related_emails = db.query(Email).filter(
        Email.user_id == current_user.id,
        Email.sender_email == email.sender_email,
        Email.id != email_id
    ).order_by(desc(Email.received_at)).limit(3).all()

    if related_emails:
        related_context = "\n\nRECENT EMAILS FROM SAME SENDER:\n"
        for rel in related_emails:
            related_context += f"- [{rel.received_at.strftime('%Y-%m-%d')}] {rel.subject}\n"
        email_context += related_context

    context_used = ["email_content", "attachments", "sara_analysis"]
    if related_emails:
        context_used.append("sender_history")

    # Call LLM
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": f"""You are Sara, David's AI assistant. You're helping David understand and respond to an email.
You have full context about this email including its content, attachments, and your prior analysis.
Be helpful, concise, and actionable. If the email requires a response, you can draft one.

{email_context}"""
                        },
                        {"role": "user", "content": request.message}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"}
            )

            if response.status_code != 200:
                raise Exception(f"LLM request failed: {response.status_code}")

            data = response.json()
            assistant_response = data["choices"][0]["message"]["content"]

            return EmailChatResponse(
                response=assistant_response,
                email_id=email_id,
                context_used=context_used
            )

    except Exception as e:
        logger.error(f"Email chat error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process chat request")


@router.post("/sync")
async def trigger_sync(
    current_user: User = Depends(get_current_user)
):
    """Manually trigger an email sync."""
    from app.tasks.email_sync import sync_emails

    sync_emails.delay()

    return {"status": "sync_queued", "message": "Email sync has been triggered"}


@router.post("/{email_id}/refresh-attachments")
async def refresh_attachments(
    email_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Refresh/fetch attachments from Graph API for an existing email.
    Use this if attachments weren't synced initially.
    """
    from app.services.msgraph_service import get_msgraph_service, is_riskninja_relevant
    import asyncio

    email = db.query(Email).filter(
        Email.id == email_id,
        Email.user_id == current_user.id
    ).first()

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    try:
        msgraph = get_msgraph_service()

        # Fetch attachments from Graph API
        attachments = await msgraph.get_attachments(email.mailbox, email_id)

        new_count = 0
        for att in attachments:
            # Check if attachment already exists
            existing = db.query(EmailAttachment).filter(
                EmailAttachment.id == att.id
            ).first()

            if existing:
                continue

            # Detect RiskNinja relevance
            is_rn = is_riskninja_relevant(
                att.name,
                email.subject,
                (email.body_text or "")[:1000]
            )

            # Create attachment record
            attachment = EmailAttachment(
                id=att.id,
                email_id=email_id,
                filename=att.name,
                content_type=att.content_type,
                size=att.size,
                is_inline=att.is_inline,
                is_riskninja_relevant=is_rn
            )
            db.add(attachment)
            new_count += 1

        db.commit()

        return {
            "status": "ok",
            "email_id": email_id,
            "attachments_found": len(attachments),
            "new_attachments": new_count
        }

    except Exception as e:
        logger.error(f"Failed to refresh attachments: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch attachments: {str(e)}")
