from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class SemanticSummary(Base):
    __tablename__ = "semantic_summary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    scope = Column(String, nullable=False)  # session:XYZ, daily:YYYY-MM-DD, weekly:YYYY-WW, topic:slug
    summary = Column(Text, nullable=False)
    embedding = Column(Vector(settings.embedding_dim), nullable=False)
    coverage = Column(JSONB, nullable=False)  # {"episode_ids": [...]} or {"date_range": ["start", "end"]}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    
    def __repr__(self):
        return f"<SemanticSummary(scope='{self.scope}', summary='{self.summary[:30]}...')>"