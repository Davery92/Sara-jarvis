"""Schemas for the Content Inbox feature."""
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class ShareURLRequest(BaseModel):
    url: str
    title: Optional[str] = None


class ShareTextRequest(BaseModel):
    text: str
    title: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str  # "kept" or "discarded"


class SharedContentSummary(BaseModel):
    id: str
    content_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    original_url: Optional[str] = None
    status: str
    extraction_status: str
    word_count: Optional[int] = None
    shared_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SharedContentDetail(SharedContentSummary):
    extracted_text: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    discussed: bool = False
    consolidated: bool = False
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    storage_key: Optional[str] = None
    read_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    episode_id: Optional[str] = None

    class Config:
        from_attributes = True


class InboxStats(BaseModel):
    unread: int = 0
    read: int = 0
    kept: int = 0
    total: int = 0
