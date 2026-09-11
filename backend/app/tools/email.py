"""
Email tools for Sara to search and read emails.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
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
        return """Search through emails and list what matches. Filter by:
- query: Text search in subject, body, and attachment filenames
- sender: Filter by sender email address
- category: Filter by category (support, urgent, sales, internal, newsletter, financial, notification, meeting)
- has_attachments: Only emails with attachments
- is_riskninja: Only RiskNinja-relevant emails
- days_back: How far back to search (default 7 days)
- unread_only: Only unread emails
- limit: How many to return (default 5)
Returns subject, sender, date and attachment names — NOT the message bodies.
Use email_read on one id when you need the body. Search results carry each
attachment's id, which is what files_to_studio and email_attachment_read take."""

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
                    "description": "Maximum number of results (default 5, max 50)"
                },
                "include_body": {
                    "type": "boolean",
                    "description": (
                        "Include each email's summary/preview text. Default false — "
                        "leave it off unless you actually need the content, or 20 "
                        "emails at 30k chars each will blow the context budget."
                    )
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
        # Default 5, not 20. On 2026-09-11 four email_search calls in one turn
        # returned 20 emails each at ~30k chars and the follow-up request was
        # refused with "prompt alone has 52684 tokens".
        limit = min(kwargs.get("limit") or 5, 50)
        include_body = bool(kwargs.get("include_body", False))

        db = next(get_db())
        try:
            # Base query
            q = db.query(Email).filter(Email.user_id == user_id)

            # Date filter
            since_date = datetime.now(timezone.utc) - timedelta(days=days_back)
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

                row = {
                    "id": email.id,
                    "subject": email.subject,
                    "from": f"{email.sender_name} <{email.sender_email}>" if email.sender_name else email.sender_email,
                    "received_at": email.received_at.isoformat() if email.received_at else None,
                    "category": email.category,
                    "importance": email.importance_score,
                    "is_read": email.is_read,
                    "has_attachments": len(atts) > 0,
                    "attachment_count": len(atts),
                    "attachments": att_list,
                    "action_required": email.action_required
                }
                if include_body:
                    row["summary"] = (
                        email.summary or (email.body_preview[:200] if email.body_preview else None)
                    )
                results.append(row)

            # The message is a status line, never an answer — name the items so
            # that even a degraded path has something real to say.
            _titles = ", ".join(
                (r["subject"] or "(no subject)")[:60] for r in results[:5]
            )
            return ToolResult(
                success=True,
                message=(
                    f"{len(results)} email(s): {_titles}" if results
                    else "No emails matched that search."
                ),
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
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

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


# How many filenames a files_to_studio status line names before it summarises.
# The full list is always in `data`.
_MESSAGE_FILENAME_LIMIT = 8


class FilesToStudioTool(BaseTool):
    """File email attachments into the Studio as downloadable artifacts.

    Harness rebuild Phase 4. On 2026-09-11 David asked, four times, for the
    attachments on Jim's emails to end up somewhere he could open them, and
    got back capability essays: "I can read them into memory", "I can
    consolidate them into a note", "that's a coding-agent job". Every piece
    needed already existed — EmailAttachment.minio_bucket/minio_key, the
    Artifact(artifact_type="file") shape, GET /api/artifacts/{id}/download,
    and an iOS Studio that lists file artifacts and hands them to the share
    sheet. Nothing joined them up. This does.
    """

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "files_to_studio"

    @property
    def description(self) -> str:
        return (
            "Put email attachments into the Studio as real, downloadable files. Use this "
            "whenever David asks to download, save, grab, collect, keep or 'put somewhere' "
            "the attachments on his email — it is the answer to 'can you download those "
            "attachments and put them in a folder'. Give it attachment_ids, or email_ids "
            "(takes every non-inline attachment on those emails), or sender + days + "
            "filename_contains to find them. Each file becomes a Studio artifact he can "
            "open and share from the Studio tab of the app. Afterwards, tell him the "
            "filenames and that they are in the Studio. Do NOT offer to 'read them into "
            "memory' or 'consolidate them into a note' instead — that is a different thing "
            "and not what he asked for."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "attachment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific attachment ids (from email_search / email_read results).",
                },
                "email_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Email ids — files every non-inline attachment on each.",
                },
                "sender": {
                    "type": "string",
                    "description": "Find attachments on emails from this sender (partial match).",
                },
                "days": {
                    "type": "integer",
                    "description": "How far back to look when using `sender` (default 30).",
                },
                "filename_contains": {
                    "type": "string",
                    "description": "Only attachments whose filename contains this text.",
                },
                "title": {
                    "type": "string",
                    "description": "What to call this group in the Studio, e.g. \"Jim's tools\".",
                },
                "skip_duplicates": {
                    "type": "boolean",
                    "description": "Skip files already in the Studio by (filename, size). Default true.",
                },
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        import uuid as _uuid

        from app.models.email import Email, EmailAttachment
        from app.models.artifact import Artifact

        attachment_ids = kwargs.get("attachment_ids") or []
        email_ids = kwargs.get("email_ids") or []
        sender = (kwargs.get("sender") or "").strip()
        filename_contains = (kwargs.get("filename_contains") or "").strip()
        try:
            days = int(kwargs.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        title = (kwargs.get("title") or "").strip()
        skip_duplicates = kwargs.get("skip_duplicates")
        skip_duplicates = True if skip_duplicates is None else bool(skip_duplicates)

        if not attachment_ids and not email_ids and not sender and not filename_contains:
            return ToolResult(
                success=False,
                message=(
                    "Tell me which attachments: attachment_ids, email_ids, or a sender "
                    "(optionally with filename_contains)."
                ),
            )

        db = next(get_db())
        try:
            # Ownership is enforced by always joining through Email.user_id —
            # an attachment id alone must never be enough to read bytes.
            q = (
                db.query(EmailAttachment, Email)
                .join(Email, EmailAttachment.email_id == Email.id)
                .filter(Email.user_id == user_id)
                .filter(or_(EmailAttachment.is_inline == False,  # noqa: E712
                            EmailAttachment.is_inline.is_(None)))
            )
            if attachment_ids:
                q = q.filter(EmailAttachment.id.in_(attachment_ids))
            elif email_ids:
                q = q.filter(EmailAttachment.email_id.in_(email_ids))
            else:
                if sender:
                    q = q.filter(Email.sender_email.ilike(f"%{sender}%"))
                since = datetime.now(timezone.utc) - timedelta(days=days)
                q = q.filter(Email.received_at >= since)
            if filename_contains:
                q = q.filter(EmailAttachment.filename.ilike(f"%{filename_contains}%"))

            rows = q.order_by(desc(Email.received_at)).limit(50).all()
            if not rows:
                return ToolResult(
                    success=True,
                    data={"files": [], "skipped": []},
                    message=(
                        "No attachments matched — nothing was filed. Say what you searched "
                        "for so David can point you at the right emails."
                    ),
                )

            existing_keys = set()
            if skip_duplicates:
                for art in db.query(Artifact).filter(
                    Artifact.user_id == user_id,
                    Artifact.artifact_type == "file",
                ).all():
                    c = art.content or {}
                    existing_keys.add((c.get("filename"), c.get("size")))

            from app.services.docs_ingest import DocumentProcessor

            processor = DocumentProcessor()
            group = title or "Email attachments"
            filed, skipped, failed = [], [], []

            for att, email in rows:
                if not att.minio_key:
                    failed.append({"filename": att.filename,
                                   "reason": "not downloaded to storage yet"})
                    continue
                if skip_duplicates and (att.filename, att.size) in existing_keys:
                    skipped.append(att.filename)
                    continue

                try:
                    file_bytes = processor.get_file(att.minio_key, bucket=att.minio_bucket)
                except Exception as e:
                    logger.error(
                        f"files_to_studio: fetch failed for {att.filename} "
                        f"({att.minio_bucket}/{att.minio_key}): {type(e).__name__}: {e}"
                    )
                    failed.append({"filename": att.filename, "reason": str(e)})
                    continue

                mime = att.content_type or "application/octet-stream"
                try:
                    storage_key = await processor.store_file(file_bytes, att.filename, mime)
                except Exception as e:
                    logger.error(
                        f"files_to_studio: store failed for {att.filename}: "
                        f"{type(e).__name__}: {e}"
                    )
                    failed.append({"filename": att.filename, "reason": str(e)})
                    continue

                artifact = Artifact(
                    id=str(_uuid.uuid4()),
                    user_id=user_id,
                    conversation_id=kwargs.get("_conversation_id"),
                    artifact_type="file",
                    title=att.filename,
                    content={
                        "storage_key": storage_key,
                        "filename": att.filename,
                        "mime": mime,
                        "size": att.size or len(file_bytes),
                        "source": {
                            "email_id": email.id,
                            "attachment_id": att.id,
                            "subject": email.subject,
                            "sender": email.sender_email,
                        },
                    },
                    artifact_metadata={"group": group},
                )
                db.add(artifact)
                existing_keys.add((att.filename, att.size))
                filed.append({
                    "artifact_id": artifact.id,
                    "filename": att.filename,
                    "size": att.size or len(file_bytes),
                    "download_url": f"/api/artifacts/{artifact.id}/download",
                })

            db.commit()

            # A status line is read by the model on every subsequent round, so
            # it has to stay small. Filing Jim's back catalogue produced a
            # message listing fifty filenames on the Phase 8 replay; the full
            # list is in `data`, where it belongs.
            def _name_list(names: list) -> str:
                shown = ", ".join(names[:_MESSAGE_FILENAME_LIMIT])
                extra = len(names) - _MESSAGE_FILENAME_LIMIT
                return f"{shown} (+{extra} more)" if extra > 0 else shown

            if not filed:
                if skipped:
                    return ToolResult(
                        success=True,
                        data={"files": [], "skipped": skipped},
                        message=(
                            f"Already in the Studio — {len(skipped)} file(s) are there now "
                            f"and downloadable: {_name_list(skipped)}. Nothing new to file. "
                            "Tell David they're in the Studio tab; do not call this again "
                            "with different arguments hoping for a different answer."
                        ),
                    )
                reasons = "; ".join(f"{f['filename']} ({f['reason']})" for f in failed)
                return ToolResult(
                    success=False,
                    data={"files": [], "failed": failed},
                    message=f"Couldn't file any of them: {reasons}",
                )

            names = _name_list([f["filename"] for f in filed])
            tail = f" ({len(skipped)} already there)" if skipped else ""
            if failed:
                tail += f"; {len(failed)} failed: " + "; ".join(
                    f"{f['filename']} ({f['reason']})"
                    for f in failed[:_MESSAGE_FILENAME_LIMIT]
                )
            return ToolResult(
                success=True,
                data={"files": filed, "skipped": skipped, "failed": failed, "group": group},
                message=(
                    f"Filed {len(filed)} file(s) to the Studio under '{group}': {names}{tail}"
                ),
            )

        except Exception as e:
            db.rollback()
            logger.error(f"files_to_studio failed: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Failed to file attachments: {e}")
        finally:
            db.close()


# Export tools list
EMAIL_TOOLS = [
    EmailSearchTool(),
    EmailReadTool(),
    EmailRecentTool(),
    EmailAttachmentReadTool(),
    FilesToStudioTool(),
]
