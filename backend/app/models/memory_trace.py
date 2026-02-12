"""Human-like memory trace models."""
from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.sql import func
from app.db.base import Base


class MemoryTrace(Base):
    """Individual memory trace with salience scoring."""
    __tablename__ = "memory_trace"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    salience = Column(Float, nullable=True)
    source = Column(Text, nullable=True)
    meta = Column(Text, nullable=True)


class MemoryEmbedding(Base):
    """Embedding vectors for memory traces."""
    __tablename__ = "memory_embedding"
    __table_args__ = {'extend_existing': True}

    trace_id = Column(String, primary_key=True)
    head = Column(String, primary_key=True)
    embedding = Column(Text, nullable=True)  # Vector handled at runtime
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MemoryEdge(Base):
    """Edges between memory traces forming a knowledge graph."""
    __tablename__ = "memory_edge"
    __table_args__ = {'extend_existing': True}

    src = Column(String, primary_key=True)
    dst = Column(String, primary_key=True)
    type = Column(String, primary_key=True)
    weight = Column(Float, nullable=True)
    ts = Column(DateTime(timezone=True), server_default=func.now())
