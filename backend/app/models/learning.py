"""
Learning System Models
Personalized learning environment with Socratic tutoring, knowledge acquisition,
spaced repetition, and research report generation.
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.db.base import Base
import uuid


class LearningTopic(Base):
    """Hierarchical learning topics for organizing knowledge"""
    __tablename__ = "learning_topic"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(String, ForeignKey("learning_topic.id", ondelete="SET NULL"), nullable=True)

    # Topic details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active")  # active, archived, completed
    mastery_level = Column(Float, default=0.0)  # 0.0 to 1.0
    priority = Column(Integer, default=5)  # 1-10
    meta = Column(JSONB, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    parent = relationship("LearningTopic", remote_side=[id], backref="children")
    sources = relationship("TopicSource", back_populates="topic", cascade="all, delete-orphan")
    sessions = relationship("LearningSession", back_populates="topic")
    progress_items = relationship("LearningProgress", back_populates="topic")
    artifacts = relationship("LearningArtifact", back_populates="topic")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "parent_id": self.parent_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "mastery_level": self.mastery_level,
            "priority": self.priority,
            "meta": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TopicSource(Base):
    """Web pages, PDFs, and documents for learning"""
    __tablename__ = "topic_source"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Source details
    source_type = Column(String(50), nullable=False)  # web, pdf, document, note
    url = Column(Text, nullable=True)
    title = Column(String(500), nullable=True)
    content_text = Column(Text, nullable=True)  # Full extracted text
    quality_score = Column(Float, default=0.5)  # 0.0 to 1.0
    origin_reputation = Column(Float, default=0.5)  # 0.0 to 1.0
    fetch_status = Column(String(50), default="pending")  # pending, fetching, fetched, failed
    meta = Column(JSONB, default=dict)  # author, date, citations, etc.

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    topic = relationship("LearningTopic", back_populates="sources")
    chunks = relationship("SourceChunk", back_populates="source", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "source_type": self.source_type,
            "url": self.url,
            "title": self.title,
            "quality_score": self.quality_score,
            "origin_reputation": self.origin_reputation,
            "fetch_status": self.fetch_status,
            "meta": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SourceChunk(Base):
    """Semantic chunks with embeddings for RAG retrieval"""
    __tablename__ = "source_chunk"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(String, ForeignKey("topic_source.id", ondelete="CASCADE"), nullable=False)

    # Chunk details
    chunk_idx = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    breadcrumb = Column(String(500), nullable=True)  # Section > Subsection hierarchy
    embedding = Column(Vector(1024), nullable=False)
    concept_tags = Column(JSONB, default=list)
    analogy_version = Column(JSONB, nullable=True)  # {"text": "...", "domain": "...", "unknown_terms": [...]}

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    source = relationship("TopicSource", back_populates="chunks")

    def to_dict(self):
        return {
            "id": self.id,
            "source_id": self.source_id,
            "chunk_idx": self.chunk_idx,
            "text": self.text,
            "breadcrumb": self.breadcrumb,
            "concept_tags": self.concept_tags or [],
            "analogy_version": self.analogy_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class LearningSession(Base):
    """Time tracking for study sessions"""
    __tablename__ = "learning_session"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="SET NULL"), nullable=True)

    # Session details
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    session_type = Column(String(50), nullable=True)  # study, review, practice, research
    notes = Column(Text, nullable=True)
    meta = Column(JSONB, default=dict)

    # Relationships
    user = relationship("User")
    topic = relationship("LearningTopic", back_populates="sessions")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "topic_id": self.topic_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_minutes": self.duration_minutes,
            "session_type": self.session_type,
            "notes": self.notes,
            "meta": self.meta or {},
        }


class LearningProgress(Base):
    """Spaced repetition state using SM-2 algorithm"""
    __tablename__ = "learning_progress"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="CASCADE"), nullable=True)
    source_id = Column(String, ForeignKey("topic_source.id", ondelete="CASCADE"), nullable=True)

    # What is being learned
    concept = Column(String(500), nullable=True)

    # SM-2 algorithm state
    ease_factor = Column(Float, default=2.5)
    interval_days = Column(Integer, default=1)
    repetitions = Column(Integer, default=0)
    next_review_at = Column(DateTime(timezone=True), server_default=func.now())
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    quality_history = Column(JSONB, default=list)  # [{date, quality_score}]
    review_mode = Column(String(50), nullable=True)  # Last review mode used
    review_mode_history = Column(JSONB, default=list)  # [{mode, quality, date}]

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    topic = relationship("LearningTopic", back_populates="progress_items")
    source = relationship("TopicSource")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "topic_id": self.topic_id,
            "source_id": self.source_id,
            "concept": self.concept,
            "ease_factor": self.ease_factor,
            "interval_days": self.interval_days,
            "repetitions": self.repetitions,
            "next_review_at": self.next_review_at.isoformat() if self.next_review_at else None,
            "last_reviewed_at": self.last_reviewed_at.isoformat() if self.last_reviewed_at else None,
            "quality_history": self.quality_history or [],
            "review_mode": self.review_mode,
            "review_mode_history": self.review_mode_history or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TopicScratchpad(Base):
    """Per-topic notes visible to Sara during learning"""
    __tablename__ = "topic_scratchpad"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Content
    content = Column(Text, nullable=False, default="")
    version = Column(Integer, default=1)

    # Session state for continuity
    session_state = Column(JSONB, default=dict)  # Stores summary, open_questions, concepts_in_progress, stuck_points, mastery_signals
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)

    # Persisted curriculum (LLM-generated learning path)
    curriculum = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Unique constraint: one scratchpad per topic per user
    __table_args__ = (
        UniqueConstraint('topic_id', 'user_id', name='uq_scratchpad_topic_user'),
    )

    # Relationships
    user = relationship("User")
    topic = relationship("LearningTopic")

    def to_dict(self):
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "user_id": self.user_id,
            "content": self.content,
            "version": self.version,
            "session_state": self.session_state or {},
            "last_interaction_at": self.last_interaction_at.isoformat() if self.last_interaction_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchReport(Base):
    """Generated research synthesis reports"""
    __tablename__ = "research_report"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="SET NULL"), nullable=True)

    # Report details
    question = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    full_content = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)  # 0.0 to 1.0
    novelty_score = Column(Float, nullable=True)  # 0.0 to 1.0
    sources_used = Column(JSONB, default=list)  # [{url, title, contribution}]
    report_type = Column(String(50), default="quick")  # quick, deep
    status = Column(String(50), default="pending")  # pending, in_progress, completed, failed
    store_in_knowledge = Column(Boolean, default=False)
    meta = Column(JSONB, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")
    topic = relationship("LearningTopic")
    jobs = relationship("ResearchJob", back_populates="report", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "topic_id": self.topic_id,
            "question": self.question,
            "summary": self.summary,
            "full_content": self.full_content,
            "confidence": self.confidence,
            "novelty_score": self.novelty_score,
            "sources_used": self.sources_used or [],
            "report_type": self.report_type,
            "status": self.status,
            "store_in_knowledge": self.store_in_knowledge,
            "meta": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ResearchJob(Base):
    """Background job tracking for deep research"""
    __tablename__ = "research_job"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    report_id = Column(String, ForeignKey("research_report.id", ondelete="CASCADE"), nullable=True)

    # Job state
    status = Column(String(50), default="queued")  # queued, running, completed, failed
    progress = Column(Integer, default=0)  # 0-100
    current_step = Column(Text, nullable=True)
    search_queries = Column(JSONB, default=list)
    sources_found = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")
    report = relationship("ResearchReport", back_populates="jobs")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "report_id": self.report_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "search_queries": self.search_queries or [],
            "sources_found": self.sources_found,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TopicConnection(Base):
    """Semantic relationships between learning topics"""
    __tablename__ = "topic_connection"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source_topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="CASCADE"), nullable=False)
    target_topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="CASCADE"), nullable=False)

    # Connection details
    connection_type = Column(String(50), nullable=False)  # prerequisite, related, builds_on, contrasts, applies_to
    strength = Column(Float, default=0.5)  # 0.0 to 1.0, semantic similarity or manual weight
    description = Column(Text, nullable=True)  # Optional explanation of the relationship
    auto_generated = Column(Boolean, default=False)  # True if created by semantic analysis
    confirmed = Column(Boolean, default=False)  # True if user confirmed auto-generated connection

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Unique constraint: one connection per topic pair per user per type
    __table_args__ = (
        UniqueConstraint('user_id', 'source_topic_id', 'target_topic_id', 'connection_type',
                        name='uq_topic_connection_pair'),
    )

    # Relationships
    user = relationship("User")
    source_topic = relationship("LearningTopic", foreign_keys=[source_topic_id])
    target_topic = relationship("LearningTopic", foreign_keys=[target_topic_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_topic_id": self.source_topic_id,
            "target_topic_id": self.target_topic_id,
            "connection_type": self.connection_type,
            "strength": self.strength,
            "description": self.description,
            "auto_generated": self.auto_generated,
            "confirmed": self.confirmed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class LearningArtifact(Base):
    """Canvas diagrams using React Flow (concept maps, mind maps, etc.)"""
    __tablename__ = "learning_artifact"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="SET NULL"), nullable=True)

    # Artifact details
    artifact_type = Column(String(50), nullable=False)  # concept_map, mind_map, flowchart, comparison
    title = Column(String(255), nullable=True)
    content = Column(JSONB, nullable=False, default=dict)  # React Flow nodes/edges
    version = Column(Integer, default=1)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    topic = relationship("LearningTopic", back_populates="artifacts")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "topic_id": self.topic_id,
            "artifact_type": self.artifact_type,
            "title": self.title,
            "content": self.content or {},
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
