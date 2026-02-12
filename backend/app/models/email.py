"""Email sync models for Microsoft Graph integration."""
from sqlalchemy import (
    Column, String, Text, DateTime, ForeignKey, Float, Boolean, Integer
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class Email(Base):
    """
    Synced email from Microsoft Graph.
    Stores email metadata, content, and Sara's analysis.
    """
    __tablename__ = "email"

    # Primary key is the Graph message ID
    id = Column(String, primary_key=True)

    # User ownership (for multi-user support)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Which mailbox this email was synced from
    mailbox = Column(String, nullable=False)

    # Email metadata
    conversation_id = Column(String, index=True)
    subject = Column(String, nullable=False)
    sender_email = Column(String, nullable=False, index=True)
    sender_name = Column(String)
    received_at = Column(DateTime(timezone=True), nullable=False, index=True)
    importance = Column(String, default="normal")  # low, normal, high
    is_read = Column(Boolean, default=False)
    internet_message_id = Column(String)  # For threading
    parent_folder_id = Column(String)

    # Email content
    body_preview = Column(Text)  # First 255 chars
    body_text = Column(Text)  # Full plain text content
    body_html = Column(Text)  # Original HTML if available

    # Recipients (stored as JSON for flexibility)
    to_recipients = Column(JSONB, default=list)  # [{"email": "", "name": ""}]
    cc_recipients = Column(JSONB, default=list)

    # Sara's analysis
    category = Column(String, index=True)  # support, urgent, sales, internal, newsletter, personal, financial
    importance_score = Column(Float, default=0.0)  # 0.0 to 1.0
    summary = Column(Text)  # Sara's AI-generated summary
    action_required = Column(Boolean, default=False)
    analyzed_at = Column(DateTime(timezone=True))

    # Notification tracking
    notification_sent = Column(Boolean, default=False)
    notification_sent_at = Column(DateTime(timezone=True))

    # Calendar event tracking
    has_meeting = Column(Boolean, default=False)
    calendar_event_id = Column(String, nullable=True)  # CalendarEvent.id if created
    calendar_event_created_at = Column(DateTime(timezone=True), nullable=True)

    # Sync metadata
    synced_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    attachments = relationship("EmailAttachment", back_populates="email", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Email(id='{self.id[:20]}...', subject='{self.subject[:30]}...')>"


class EmailAttachment(Base):
    """
    Email attachment stored in MinIO.
    Tracks both the original attachment metadata and its storage location.
    """
    __tablename__ = "email_attachment"

    # Primary key is the Graph attachment ID
    id = Column(String, primary_key=True)

    # Parent email
    email_id = Column(String, ForeignKey("email.id", ondelete="CASCADE"), nullable=False)

    # Attachment metadata from Graph
    filename = Column(String, nullable=False)
    content_type = Column(String)  # MIME type
    size = Column(Integer, default=0)  # bytes
    is_inline = Column(Boolean, default=False)
    content_id = Column(String)  # For inline attachments

    # MinIO storage location
    minio_bucket = Column(String)  # sara-docs or riskninja-docs
    minio_key = Column(String)  # Storage path within bucket

    # RiskNinja detection
    is_riskninja_relevant = Column(Boolean, default=False)

    # Sara's filing to Projects
    filed_to_project_id = Column(String, nullable=True)  # DevProject.id if filed
    filed_to_folder_id = Column(String, nullable=True)   # ProjectFolder.id (Sara's Findings)
    filed_to_file_id = Column(String, nullable=True)     # ProjectFile.id created
    filed_at = Column(DateTime(timezone=True), nullable=True)
    filing_analysis = Column(Text, nullable=True)        # Sara's reasoning for importance

    # Timestamps
    downloaded_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    email = relationship("Email", back_populates="attachments")

    def __repr__(self):
        return f"<EmailAttachment(id='{self.id[:20]}...', filename='{self.filename}')>"


class EmailSyncState(Base):
    """
    Tracks sync state for each mailbox to enable incremental syncing.
    """
    __tablename__ = "email_sync_state"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # User who owns this sync state
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Mailbox being synced
    mailbox = Column(String, nullable=False, index=True)

    # Last successful sync timestamp
    last_sync_at = Column(DateTime(timezone=True))

    # Stats from last sync
    last_sync_count = Column(Integer, default=0)
    last_sync_errors = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<EmailSyncState(mailbox='{self.mailbox}', last_sync='{self.last_sync_at}')>"
