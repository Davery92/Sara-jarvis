"""Note connection model for knowledge garden links."""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class NoteConnection(Base):
    """Represents a connection between two notes in the knowledge garden."""
    __tablename__ = "note_connection"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source_note_id = Column(String, ForeignKey("note.id", ondelete="CASCADE"), nullable=False)
    target_note_id = Column(String, ForeignKey("note.id", ondelete="CASCADE"), nullable=False)
    connection_type = Column(String, nullable=False)  # 'reference', 'semantic', 'temporal'
    strength = Column(Integer, default=50)  # 0-100 strength score
    auto_generated = Column(String, default="true")  # true for auto-detected, false for manual
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<NoteConnection(source={self.source_note_id[:8]}, target={self.target_note_id[:8]}, type={self.connection_type})>"
