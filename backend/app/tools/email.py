"""
Email tools for Sara to search and read emails.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
import logging

logger = logging.getLogger(__name__)


class EmailSearchTool(BaseTool):
    """Search emails by various criteria"""

    @property
    def name(self) -> str:
        return "email_search"

    @property
    def description(self) -> str:
        return """Search through emails. Can filter by:
- query: Text search in subject, body, and attachment filenames
- sender: Filter by sender email address
- category: Filter by category (support, urgent, sales, internal, newsletter, financial, notification, meeting)
- has_attachments: Only emails with attachments
- is_riskninja: Only RiskNinja-relevant emails
- days_back: How far back to search (default 7 days)
- unread_only: Only unread emails
Returns up to 20 most recent matching emails."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for in subject, body, and attachment filenames"
                },
                "sender": {
                    "type": "string",
                    "description": "Filter by sender email address (partial match)"
                },
                "category": {
                    "type": "string",
                    "enum": ["support", "urgent", "sales", "internal", "newsletter", "financial", "notification", "meeting"],
                    "description": "Filter by email category"
                },
                "has_attachments": {
                    "type": "boolean",
                    "description": "Only return emails with attachments"
                },
                "is_riskninja": {
                    "type": "boolean",
                    "description": "Only return emails with RiskNinja-relevant attachments"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 7)"
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Only return unread emails"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20, max 50)"
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.models.email import Email, EmailAttachment

        query_text = kwargs.get("query")
        sender = kwargs.get("sender")
        category = kwargs.get("category")
        has_attachments = kwargs.get("has_attachments", False)
        is_riskninja = kwargs.get("is_riskninja", False)
        days_back = kwargs.get("days_back", 7)
        unread_only = kwargs.get("unread_only", False)
        limit = min(kwargs.get("limit", 20), 50)

        db = next(get_db())
        try:
            # Base query
            q = db.query(Email).filter(Email.user_id == user_id)

            # Date filter
            since_date = datetime.utcnow() - timedelta(days=days_back)
            q = q.filter(Email.received_at >= since_date)

            # Text search (subject, body, AND attachment filenames)
            if query_text:
                search_pattern = f"%{query_text}%"
                q = q.filter(or_(
                    Email.subject.ilike(search_pattern),
                    Email.body_text.ilike(search_pattern),
                    Email.body_preview.ilike(search_pattern),
                    Email.id.in_(
                        db.query(EmailAttachment.email_id).filter(
                            EmailAttachment.filename.ilike(search_pattern)
                        ).distinct()
                    ),
                ))

            # Sender filter
            if sender:
                q = q.filter(Email.sender_email.ilike(f"%{sender}%"))

            # Category filter
            if category:
                q = q.filter(Email.category == category)

            # Unread filter
            if unread_only:
                q = q.filter(Email.is_read == False)

            # Has attachments filter
            if has_attachments:
                q = q.filter(Email.id.in_(
                    db.query(EmailAttachment.email_id).distinct()
                ))

            # RiskNinja filter
            if is_riskninja:
                q = q.filter(Email.id.in_(
                    db.query(EmailAttachment.email_id).filter(
                        EmailAttachment.is_riskninja_relevant == True
                    ).distinct()
                ))

            # Order by received date descending
            q = q.order_by(desc(Email.received_at))
            q = q.limit(limit)

            emails = q.all()

            # Format results
            results = []
            for email in emails:
                # Get attachments
                atts = db.query(EmailAttachment).filter(
                    EmailAttachment.email_id == email.id
                ).all()

                att_list = [
                    {
                        "id": att.id,
                        "filename": att.filename,
                        "content_type": att.content_type,
                        "size": att.size,
                        "download_url": f"/email/{email.id}/attachments/{att.id}/download",
                    }
                    for att in atts
                ] if atts else []

                results.append({
                    "id": email.id,
                    "subject": email.subject,
                    "from": f"{email.sender_name} <{email.sender_email}>" if email.sender_name else email.sender_email,
                    "received_at": email.received_at.isoformat() if email.received_at else None,
                    "category": email.category,
                    "importance": email.importance_score,
                    "summary": email.summary or email.body_preview[:200] if email.body_preview else None,
                    "is_read": email.is_read,
                    "has_attachments": len(atts) > 0,
                    "attachment_count": len(atts),
                    "attachments": att_list,
                    "action_required": email.action_required
                })

            return ToolResult(
                success=True,
                message=f"Found {len(results)} emails",
                data={"emails": results, "count": len(results)}
            )

        except Exception as e:
            logger.error(f"Email search error: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to search emails: {str(e)}"
            )
        finally:
            db.close()


class EmailReadTool(BaseTool):
    """Read the full content of a specific email"""

    @property
    def name(self) -> str:
        return "email_read"

    @property
    def description(self) -> str:
        return "Read the full content of a specific email by ID. Returns complete email body, attachments list, and analysis."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The ID of the email to read"
                }
            },
            "required": ["email_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.models.email import Email, EmailAttachment

        email_id = kwargs.get("email_id")
        if not email_id:
            return ToolResult(success=False, message="email_id is required")

        db = next(get_db())
        try:
            email = db.query(Email).filter(
                Email.id == email_id,
                Email.user_id == user_id
            ).first()

            if not email:
                return ToolResult(
                    success=False,
                    message=f"Email not found: {email_id}"
                )

            # Get attachments
            attachments = db.query(EmailAttachment).filter(
                EmailAttachment.email_id == email_id
            ).all()

            attachment_list = [
                {
                    "id": att.id,
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "size": att.size,
                    "is_riskninja_relevant": att.is_riskninja_relevant,
                    "is_downloaded": att.minio_key is not None,
                    "download_url": f"/email/{email_id}/attachments/{att.id}/download",
                }
                for att in attachments
            ]

            result = {
                "id": email.id,
                "subject": email.subject,
                "from": {
                    "name": email.sender_name,
                    "email": email.sender_email
                },
                "to": email.to_recipients,
                "cc": email.cc_recipients,
                "received_at": email.received_at.isoformat() if email.received_at else None,
                "body": email.body_text or email.body_preview,
                "category": email.category,
                "importance_score": email.importance_score,
                "summary": email.summary,
                "action_required": email.action_required,
                "is_read": email.is_read,
                "has_meeting": email.has_meeting,
                "calendar_event_id": email.calendar_event_id,
                "attachments": attachment_list
            }

            return ToolResult(
                success=True,
                message=f"Email: {email.subject}",
                data=result
            )

        except Exception as e:
            logger.error(f"Email read error: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to read email: {str(e)}"
            )
        finally:
            db.close()


class EmailRecentTool(BaseTool):
    """Get recent emails summary"""

    @property
    def name(self) -> str:
        return "email_recent"

    @property
    def description(self) -> str:
        return "Get a summary of recent emails. Use this to quickly see what's new in the inbox. Returns unread count, important emails, and recent messages."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to look (default 24)"
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.models.email import Email, EmailAttachment

        hours = kwargs.get("hours", 24)
        since = datetime.utcnow() - timedelta(hours=hours)

        db = next(get_db())
        try:
            # Get counts
            total_recent = db.query(Email).filter(
                Email.user_id == user_id,
                Email.received_at >= since
            ).count()

            unread_count = db.query(Email).filter(
                Email.user_id == user_id,
                Email.received_at >= since,
                Email.is_read == False
            ).count()

            action_required = db.query(Email).filter(
                Email.user_id == user_id,
                Email.received_at >= since,
                Email.action_required == True
            ).count()

            # Get important emails (high importance or support/urgent)
            important_emails = db.query(Email).filter(
                Email.user_id == user_id,
                Email.received_at >= since,
                or_(
                    Email.importance_score >= 0.7,
                    Email.category.in_(["support", "urgent"])
                )
            ).order_by(desc(Email.received_at)).limit(5).all()

            # Get most recent emails
            recent_emails = db.query(Email).filter(
                Email.user_id == user_id,
                Email.received_at >= since
            ).order_by(desc(Email.received_at)).limit(10).all()

            # Category breakdown
            categories = {}
            category_results = db.query(Email.category).filter(
                Email.user_id == user_id,
                Email.received_at >= since,
                Email.category.isnot(None)
            ).all()
            for (cat,) in category_results:
                categories[cat] = categories.get(cat, 0) + 1

            # Format important emails
            important_list = [
                {
                    "subject": e.subject,
                    "from": e.sender_email,
                    "category": e.category,
                    "summary": e.summary[:100] if e.summary else e.body_preview[:100] if e.body_preview else None
                }
                for e in important_emails
            ]

            # Format recent emails
            recent_list = [
                {
                    "subject": e.subject,
                    "from": e.sender_email,
                    "received": e.received_at.strftime("%I:%M %p") if e.received_at else None,
                    "category": e.category
                }
                for e in recent_emails
            ]

            return ToolResult(
                success=True,
                message=f"{total_recent} emails in the last {hours} hours ({unread_count} unread)",
                data={
                    "summary": {
                        "total": total_recent,
                        "unread": unread_count,
                        "action_required": action_required,
                        "hours": hours
                    },
                    "categories": categories,
                    "important": important_list,
                    "recent": recent_list
                }
            )

        except Exception as e:
            logger.error(f"Email recent error: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get recent emails: {str(e)}"
            )
        finally:
            db.close()


class EmailAttachmentReadTool(BaseTool):
    """Read the text content of an email attachment"""

    @property
    def name(self) -> str:
        return "email_attachment_read"

    @property
    def description(self) -> str:
        return (
            "Read the text content of an email attachment. Supports .docx, .pdf, .txt, .csv, "
            "and other text-based formats. Use this after email_read to extract the actual "
            "content of attached documents. Returns extracted text."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The ID of the email containing the attachment"
                },
                "attachment_id": {
                    "type": "string",
                    "description": "The ID of the attachment to read (from email_read results)"
                }
            },
            "required": ["email_id", "attachment_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.models.email import Email, EmailAttachment

        email_id = kwargs.get("email_id")
        attachment_id = kwargs.get("attachment_id")
        if not email_id or not attachment_id:
            return ToolResult(success=False, message="email_id and attachment_id are required")

        db = next(get_db())
        try:
            # Verify email ownership
            email = db.query(Email).filter(
                Email.id == email_id,
                Email.user_id == user_id
            ).first()
            if not email:
                return ToolResult(success=False, message=f"Email not found: {email_id}")

            # Get attachment
            attachment = db.query(EmailAttachment).filter(
                EmailAttachment.id == attachment_id,
                EmailAttachment.email_id == email_id
            ).first()
            if not attachment:
                return ToolResult(success=False, message=f"Attachment not found: {attachment_id}")

            if not attachment.minio_key or not attachment.minio_bucket:
                return ToolResult(
                    success=False,
                    message=f"Attachment '{attachment.filename}' has not been downloaded to storage yet"
                )

            # Download from MinIO
            try:
                from minio import Minio
                from app.core.config import settings

                minio_url = settings.minio_url.replace("http://", "").replace("https://", "")
                minio_client = Minio(
                    minio_url,
                    access_key=settings.minio_access_key,
                    secret_key=settings.minio_secret_key,
                    secure=False
                )

                response = minio_client.get_object(attachment.minio_bucket, attachment.minio_key)
                file_content = response.read()
                response.close()
                response.release_conn()
            except Exception as e:
                logger.error(f"MinIO download error for attachment {attachment_id}: {e}")
                return ToolResult(success=False, message=f"Failed to download attachment from storage: {e}")

            # Extract text using DocumentProcessor
            try:
                from app.services.docs_ingest import DocumentProcessor
                processor = DocumentProcessor()
                text, metadata = processor.extract_text(
                    file_content,
                    attachment.content_type or "application/octet-stream",
                    attachment.filename
                )
            except ImportError:
                # Fallback: try basic text decode
                try:
                    text = file_content.decode("utf-8", errors="ignore")
                    metadata = {"fallback": True}
                except Exception:
                    return ToolResult(
                        success=False,
                        message=f"Cannot extract text from '{attachment.filename}' ({attachment.content_type})"
                    )
            except Exception as e:
                logger.error(f"Text extraction error for {attachment.filename}: {e}")
                return ToolResult(
                    success=False,
                    message=f"Failed to extract text from '{attachment.filename}': {e}"
                )

            if not text or not text.strip():
                return ToolResult(
                    success=False,
                    message=f"No text content could be extracted from '{attachment.filename}'"
                )

            # Truncate if very long (keep first ~15k chars for LLM context)
            max_chars = 15000
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars] + f"\n\n[... truncated, {len(text)} total characters ...]"

            return ToolResult(
                success=True,
                message=f"Extracted text from '{attachment.filename}' ({metadata.get('paragraphs', '?')} paragraphs, {metadata.get('tables', 0)} tables)",
                data={
                    "filename": attachment.filename,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size,
                    "text": text,
                    "metadata": metadata,
                    "truncated": truncated
                }
            )

        except Exception as e:
            logger.error(f"Email attachment read error: {e}")
            return ToolResult(success=False, message=f"Failed to read attachment: {str(e)}")
        finally:
            db.close()


# Export tools list
EMAIL_TOOLS = [
    EmailSearchTool(),
    EmailReadTool(),
    EmailRecentTool(),
    EmailAttachmentReadTool()
]
