from sqlalchemy import Column, String, DateTime, Integer, BigInteger, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class TokenUsage(Base):
    """Track token usage across all LLM calls"""
    __tablename__ = "token_usage"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('app_user.id'), nullable=True, index=True)

    # Request metadata
    endpoint = Column(String(255), nullable=False)  # e.g., '/chat', '/fitness/conversational'
    model = Column(String(100), nullable=False)  # e.g., 'Qwen3.5-122B-A10B'
    operation_type = Column(String(50), nullable=False)  # 'chat', 'embedding', 'tool_call'

    # Token counts
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)

    # Optional metadata
    session_id = Column(String(36), nullable=True, index=True)
    request_metadata = Column(JSONB, nullable=True)  # Tool names, temperature, etc.

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<TokenUsage(model='{self.model}', total={self.total_tokens})>"


class TokenUsageAggregate(Base):
    """Aggregate token usage for fast stats - updated by triggers or periodic job"""
    __tablename__ = "token_usage_aggregate"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('app_user.id'), nullable=True, index=True)

    # Cumulative totals (all time since last reset)
    total_prompt_tokens = Column(BigInteger, nullable=False, default=0)
    total_completion_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    total_requests = Column(BigInteger, nullable=False, default=0)

    # Reset tracking
    last_reset_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TokenUsageAggregate(total={self.total_tokens}, requests={self.total_requests})>"
