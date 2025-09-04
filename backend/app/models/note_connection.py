from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class NoteConnection(Base):
    __tablename__ = "note_connection"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source_note_id = Column(String, ForeignKey("note.id", ondelete="CASCADE"), nullable=False)
    target_note_id = Column(String, ForeignKey("note.id", ondelete="CASCADE"), nullable=False)
    connection_type = Column(String, nullable=False, default="reference")  # reference, semantic, temporal
    strength = Column(Integer, nullable=False, default=50)  # 0-100
    auto_generated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User")
    source_note = relationship("Note", foreign_keys=[source_note_id])
    target_note = relationship("Note", foreign_keys=[target_note_id])
    
    def __repr__(self):
        return f"<NoteConnection(source='{self.source_note_id}', target='{self.target_note_id}', type='{self.connection_type}')>"