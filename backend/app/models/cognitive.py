"""
Cognitive Enhancement Models for Sara

This module contains models for:
1. SaraReflection - Sara's self-knowledge and learning from interactions
2. RelationshipState - Tracking the Sara-David relationship evolution
3. Hypothesis - Sara's explicit beliefs/theories about David
4. ReasoningTrace - Captured thinking from gpt-oss
5. Prediction - Calibration tracking for uncertainty
"""

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class SaraReflection(Base):
    """
    Sara's self-reflections and learnings about herself.

    Reflection types:
    - "mistake": Sara made an error and learned from it
    - "pattern": Sara noticed a pattern in her own behavior
    - "preference": Sara learned what works well with David
    - "growth": Sara's understanding deepened over time
    """
    __tablename__ = "sara_reflection"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    reflection_type = Column(String(50), nullable=False)  # mistake, pattern, preference, growth
    domain = Column(String(100), nullable=True)  # fitness, work, personal, technical, etc.
    content = Column(Text, nullable=False)  # The actual reflection/learning
    source_episodes = Column(JSONB, default=[])  # Episode IDs that triggered this
    confidence = Column(Float, default=0.5)  # How confident Sara is in this reflection
    times_applied = Column(Integer, default=0)  # How often this reflection influenced responses
    effectiveness_score = Column(Float, nullable=True)  # Did applying it help? (0-1)
    superseded_by = Column(String, ForeignKey('sara_reflection.id'), nullable=True)
    is_active = Column(Boolean, default=True)
    embedding = Column(Vector(settings.embedding_dim), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SaraReflection(type='{self.reflection_type}', domain='{self.domain}', content='{self.content[:50]}...')>"


class RelationshipState(Base):
    """
    Tracks the evolving relationship between Sara and David.

    Phases:
    - "early": < 10 conversations
    - "developing": 10-50 conversations
    - "established": 50-200 conversations
    - "deep": 200+ conversations
    """
    __tablename__ = "relationship_state"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    phase = Column(String(50), default='early')  # early, developing, established, deep
    total_conversations = Column(Integer, default=0)
    total_episodes = Column(Integer, default=0)
    first_interaction = Column(DateTime(timezone=True), nullable=True)
    topics_discussed = Column(JSONB, default={})  # {topic: count}
    shared_references = Column(JSONB, default=[])  # Inside jokes, recurring themes
    trust_signals = Column(JSONB, default=[])  # Evidence of trust/openness
    tension_events = Column(JSONB, default=[])  # Times user was frustrated
    communication_preferences = Column(JSONB, default={})  # Learned preferences
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<RelationshipState(phase='{self.phase}', conversations={self.total_conversations})>"


class Hypothesis(Base):
    """
    Sara's hypotheses/beliefs about David.

    Status values:
    - "active": Hypothesis is being tracked
    - "confirmed": High confidence, consistently supported
    - "refuted": Evidence contradicts it
    - "superseded": Replaced by a more refined hypothesis
    - "stale": No new evidence in a long time
    """
    __tablename__ = "hypothesis"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    statement = Column(Text, nullable=False)  # The hypothesis statement
    domain = Column(String(100), nullable=False)  # health, work, personal, technical, habits, etc.
    confidence = Column(Float, default=0.3)  # 0-1 confidence level
    evidence_for = Column(JSONB, default=[])  # [{episode_id, quote, weight, timestamp}]
    evidence_against = Column(JSONB, default=[])  # Same structure
    status = Column(String(50), default='active')
    superseded_by = Column(String, ForeignKey('hypothesis.id'), nullable=True)
    times_useful = Column(Integer, default=0)  # How often this hypothesis helped
    embedding = Column(Vector(settings.embedding_dim), nullable=True)
    first_formed = Column(DateTime(timezone=True), server_default=func.now())
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_evidence_at = Column(DateTime(timezone=True), nullable=True)

    # Confidence thresholds
    CONFIDENCE_CONFIRMED = 0.85
    CONFIDENCE_REFUTED = 0.15
    CONFIDENCE_INITIAL = 0.3

    def __repr__(self):
        return f"<Hypothesis('{self.statement[:50]}...', confidence={self.confidence:.2f}, status='{self.status}')>"


class ReasoningTrace(Base):
    """
    Captured reasoning/thinking from gpt-oss extended thinking.
    Allows answering "How did you arrive at that?" questions.
    """
    __tablename__ = "reasoning_trace"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    episode_id = Column(String, nullable=True)  # Link to episode if applicable
    conversation_id = Column(String, nullable=True)  # Session/conversation ID
    thinking_content = Column(Text, nullable=False)  # The captured thinking
    reasoning_effort = Column(String(20), nullable=True)  # low, medium, high
    tool_calls_made = Column(JSONB, default=[])  # Tools used during reasoning
    final_answer_summary = Column(Text, nullable=True)  # Brief summary of conclusion
    token_count = Column(Integer, nullable=True)  # Tokens used in thinking
    duration_ms = Column(Integer, nullable=True)  # Time spent thinking
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ReasoningTrace(effort='{self.reasoning_effort}', tokens={self.token_count})>"


class Prediction(Base):
    """
    Predictions Sara makes for calibration tracking.
    Helps measure if Sara's confidence levels are accurate.

    Good calibration: 70% confident predictions should be right ~70% of the time.
    """
    __tablename__ = "prediction"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    statement = Column(Text, nullable=False)  # What Sara predicted
    domain = Column(String(100), nullable=True)  # Domain of prediction
    confidence = Column(Float, nullable=False)  # 0-1 confidence when made
    source_episode_id = Column(String, nullable=True)  # Episode where prediction was made
    outcome = Column(String(50), nullable=True)  # correct, incorrect, unknown
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Prediction('{self.statement[:30]}...', confidence={self.confidence:.2f}, outcome='{self.outcome}')>"
