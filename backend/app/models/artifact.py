"""
Artifact Model for Canvas System
Stores code, diagrams, documents, and other interactive content
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class Artifact(Base):
    """
    Artifact model for storing canvas content

    Artifact Types:
    - code: Code snippets with language info
    - diagram: Mermaid diagrams or other visualizations
    - document: Rich text documents
    - canvas: Freeform drawing data
    - table: Tabular data

    Content Structure (varies by type):
    - code: {"code": "...", "language": "python", "output": "..."}
    - diagram: {"source": "mermaid code", "type": "mermaid"}
    - document: {"content": "html or markdown", "format": "html"}
    - canvas: {"elements": [...], "viewport": {...}}
    - table: {"columns": [...], "rows": [...]}
    """
    __tablename__ = 'artifacts'

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    conversation_id = Column(String(36), nullable=True)  # Optional link to conversation
    episode_id = Column(String(36), nullable=True)  # Optional link to specific message
    artifact_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(JSONB, nullable=False)
    artifact_metadata = Column(JSONB, nullable=True)
    is_pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
            'episode_id': self.episode_id,
            'artifact_type': self.artifact_type,
            'title': self.title,
            'content': self.content,
            'metadata': self.artifact_metadata,
            'is_pinned': self.is_pinned,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
