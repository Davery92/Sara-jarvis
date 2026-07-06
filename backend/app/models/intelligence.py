"""Intelligence report models."""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class IntelligenceReport(Base):
    """Periodic intelligence reports (weekly/monthly/quarterly)."""
    __tablename__ = "intelligence_reports"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    report_type = Column(String, nullable=False)  # weekly, monthly, quarterly
    report_date = Column(DateTime, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    full_content = Column(Text, nullable=True)
    key_insights = Column(Text, nullable=True)  # JSON array
    metrics = Column(Text, nullable=True)  # JSON object
    created_at = Column(DateTime, server_default=func.now())
