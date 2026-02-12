"""Email schemas for API responses."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime


class EmailAttachmentResponse(BaseModel):
    id: str
    filename: str
    content_type: Optional[str] = None
    size: int = 0
    is_inline: bool = False
    is_riskninja_relevant: bool = False
    has_download: bool = False  # True if stored in MinIO


class EmailResponse(BaseModel):
    id: str
    mailbox: str
    subject: str
    sender_email: str
    sender_name: Optional[str] = None
    received_at: str
    importance: str = "normal"
    is_read: bool = False
    body_preview: Optional[str] = None
    has_attachments: bool = False
    attachment_count: int = 0

    # Sara's analysis
    category: Optional[str] = None
    importance_score: Optional[float] = None
    summary: Optional[str] = None
    action_required: bool = False

    # Recipients
    to_recipients: List[Dict[str, str]] = []
    cc_recipients: List[Dict[str, str]] = []


class EmailDetailResponse(EmailResponse):
    """Full email detail including body content."""
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    conversation_id: Optional[str] = None
    internet_message_id: Optional[str] = None
    attachments: List[EmailAttachmentResponse] = []
    analyzed_at: Optional[str] = None
    synced_at: str


class EmailListResponse(BaseModel):
    """Paginated email list response."""
    emails: List[EmailResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class EmailStatsResponse(BaseModel):
    """Email dashboard statistics."""
    total_emails: int
    unread_count: int
    by_category: Dict[str, int]
    by_mailbox: Dict[str, int]
    action_required_count: int
    high_importance_count: int
    last_sync: Optional[str] = None


class EmailChatRequest(BaseModel):
    """Request for email-scoped chat."""
    message: str


class EmailChatResponse(BaseModel):
    """Response from email-scoped chat."""
    response: str
    email_id: str
    context_used: List[str] = []  # What context Sara used


class MarkReadRequest(BaseModel):
    """Request to mark email as read."""
    is_read: bool = True
