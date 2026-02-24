"""Intelligence feed item model — individual news/research items from monitored sources."""
from sqlalchemy import Column, String, Text, DateTime, Float, Boolean, Index
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class IntelligenceItem(Base):
    """A single intelligence feed item discovered by the monitor."""
    __tablename__ = "intelligence_item"
    __table_args__ = (
        Index("ix_intelligence_item_source_category", "source_category"),
        Index("ix_intelligence_item_discovered_at", "discovered_at"),
        Index("ix_intelligence_item_novelty_score", "novelty_score"),
        Index("ix_intelligence_item_relevance_score", "relevance_score"),
        Index("ix_intelligence_item_dismissed", "dismissed"),
        {'extend_existing': True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source = Column(String, nullable=False)  # e.g., "arxiv_cs_ai", "hackernews", "r_locallama"
    source_category = Column(String, nullable=False)  # ai_research, local_ai, broader_tech
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    url = Column(String, nullable=True)
    full_content = Column(Text, nullable=True)
    novelty_score = Column(Float, default=0.5)  # 0-1: how new/unique is this?
    relevance_score = Column(Float, default=0.5)  # 0-1: how relevant to David's interests?
    discovered_at = Column(DateTime, server_default=func.now())
    included_in_digest_at = Column(DateTime, nullable=True)
    notified_at = Column(DateTime, nullable=True)
    dismissed = Column(Boolean, default=False)
    digest_text = Column(Text, nullable=True)  # Latest digest that included this item
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "source_category": self.source_category,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "novelty_score": self.novelty_score,
            "relevance_score": self.relevance_score,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "included_in_digest_at": self.included_in_digest_at.isoformat() if self.included_in_digest_at else None,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "dismissed": self.dismissed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
