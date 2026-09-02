"""Durable world-event, world-model, and presence persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


class WorldEvent(Base):
    __tablename__ = "world_event"
    sequence = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False, unique=True, default=_uuid)
    schema_version = Column(Integer, nullable=False, default=2)
    user_id = Column(String, nullable=False)
    kind = Column(String(128), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    committed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source = Column(String(128), nullable=False)
    source_ref = Column(String(512), nullable=True)
    aggregate_type = Column(String(128), nullable=True)
    aggregate_id = Column(String(255), nullable=True)
    aggregate_version = Column(BigInteger, nullable=True)
    actor_type = Column(String(32), nullable=False, default="system")
    actor_id = Column(String(255), nullable=True)
    correlation_id = Column(String(128), nullable=True)
    causation_id = Column(String(36), nullable=True)
    dedupe_key = Column(String(512), nullable=False)
    payload = Column(JSON_TYPE, nullable=False, default=dict)
    provenance = Column(JSON_TYPE, nullable=False, default=dict)
    confidence = Column(Float, nullable=False, default=1.0)
    confidence_basis = Column(String(16), nullable=False, default="observed")
    sensitivity = Column(String(32), nullable=False, default="normal")
    retention_class = Column(String(32), nullable=False, default="standard")
    is_backfill = Column(Boolean, nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_world_event_user_dedupe"),
        Index("ix_world_event_user_sequence", "user_id", "sequence"),
        Index("ix_world_event_user_kind_occurred", "user_id", "kind", "occurred_at"),
        Index("ix_world_event_aggregate", "aggregate_type", "aggregate_id", "aggregate_version"),
        Index("ix_world_event_correlation", "correlation_id"),
        Index("ix_world_event_causation", "causation_id"),
    )


class WorldEventProcessing(Base):
    __tablename__ = "world_event_processing"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(String(36), ForeignKey("world_event.event_id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="pending")
    attempt_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    leased_until = Column(DateTime(timezone=True), nullable=True)
    worker_id = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    reducer_version = Column(Integer, nullable=False, default=1)
    interpreter_status = Column(String(24), nullable=False, default="not_needed")
    interpreter_attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_world_event_processing_ready", "status", "next_attempt_at", "leased_until"),)


class WorldEntity(Base):
    __tablename__ = "world_entity"
    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    kind = Column(String(64), nullable=False)
    canonical_key = Column(String(512), nullable=False)
    display_name = Column(String(512), nullable=False)
    aliases = Column(JSON_TYPE, nullable=False, default=list)
    attributes = Column(JSON_TYPE, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="active")
    merged_into_id = Column(String(36), nullable=True)
    first_event_id = Column(String(36), nullable=True)
    last_event_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "canonical_key", name="uq_world_entity_canonical"),
        Index("ix_world_entity_user_kind", "user_id", "kind"),
    )


class WorldFact(Base):
    __tablename__ = "world_fact"
    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    fact_key = Column(String(768), nullable=False)
    subject_entity_id = Column(String(36), nullable=True)
    predicate = Column(String(255), nullable=False)
    object_entity_id = Column(String(36), nullable=True)
    value = Column(JSON_TYPE, nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(24), nullable=False, default="active")
    confidence = Column(Float, nullable=False, default=1.0)
    confidence_basis = Column(String(16), nullable=False, default="observed")
    source_event_id = Column(String(36), nullable=False)
    source_ref = Column(String(512), nullable=True)
    extractor_version = Column(String(128), nullable=True)
    supersedes_fact_id = Column(String(36), nullable=True)
    retracted_by_event_id = Column(String(36), nullable=True)
    last_event_sequence = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("ix_world_fact_user_status", "user_id", "status"),
        Index("ix_world_fact_user_key", "user_id", "fact_key"),
        Index("ix_world_fact_subject_predicate", "subject_entity_id", "predicate"),
        Index("ix_world_fact_source_event", "source_event_id"),
    )


class WorldThread(Base):
    __tablename__ = "world_thread"
    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    thread_key = Column(String(768), nullable=False)
    kind = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="open")
    title = Column(Text, nullable=False)
    next_step = Column(Text, nullable=True)
    owner_entity_id = Column(String(36), nullable=True)
    counterparty_entity_id = Column(String(36), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    # What vouched for due_at: 'producer:<kind>', 'david:<kind>',
    # 'source_text:<matched substring>'. NULL whenever due_at is NULL. A model's
    # opinion is never one of these — see reducer._deterministic_due_at.
    due_provenance = Column(String(200), nullable=True)
    next_review_at = Column(DateTime(timezone=True), nullable=True)
    priority = Column(Float, nullable=False, default=0.5)
    confidence = Column(Float, nullable=False, default=1.0)
    source_event_id = Column(String(36), nullable=False)
    source_fact_ids = Column(JSON_TYPE, nullable=False, default=list)
    correlation_id = Column(String(128), nullable=True)
    last_event_sequence = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("user_id", "thread_key", name="uq_world_thread_key"),
        Index("ix_world_thread_user_status_review", "user_id", "status", "next_review_at"),
    )


class WorldAttentionItem(Base):
    __tablename__ = "world_attention_item"
    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    source_event_id = Column(String(36), nullable=False)
    source_fact_id = Column(String(36), nullable=True)
    source_thread_id = Column(String(36), nullable=True)
    domain = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    salience = Column(Float, nullable=False, default=0.0)
    novelty = Column(Float, nullable=False, default=0.0)
    urgency = Column(Float, nullable=False, default=0.0)
    uncertainty = Column(Float, nullable=False, default=0.0)
    actionability = Column(Float, nullable=False, default=0.0)
    aggregate_score = Column(Float, nullable=False, default=0.0)
    coalesce_key = Column(String(768), nullable=False)
    occurrence_count = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="queued")
    valid_until = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("user_id", "coalesce_key", name="uq_world_attention_coalesce"),
        Index("ix_world_attention_user_status_score", "user_id", "status", "aggregate_score"),
    )


class WorldEventDisposition(Base):
    __tablename__ = "world_event_disposition"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(String(36), ForeignKey("world_event.event_id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(String, nullable=False)
    reducer_version = Column(Integer, nullable=False, default=1)
    outcomes = Column(JSON_TYPE, nullable=False, default=list)
    reason = Column(Text, nullable=False)
    state_delta = Column(JSON_TYPE, nullable=False, default=dict)
    output_ids = Column(JSON_TYPE, nullable=False, default=dict)
    policy_version = Column(String(64), nullable=False, default="world-state-v1")
    model_version = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (Index("ix_world_disposition_user_created", "user_id", "created_at"),)


class WorldSnapshot(Base):
    __tablename__ = "world_snapshot"
    user_id = Column(String, primary_key=True)
    schema_version = Column(Integer, nullable=False, default=2)
    revision = Column(BigInteger, nullable=False, default=0)
    last_event_sequence = Column(BigInteger, nullable=False, default=0)
    snapshot = Column(JSON_TYPE, nullable=False, default=dict)
    coverage = Column(JSON_TYPE, nullable=False, default=dict)
    as_of = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SaraPresenceSnapshot(Base):
    __tablename__ = "sara_presence_snapshot"
    user_id = Column(String, primary_key=True)
    schema_version = Column(Integer, nullable=False, default=1)
    revision = Column(BigInteger, nullable=False, default=0)
    state = Column(String(24), nullable=False, default="resting")
    headline = Column(Text, nullable=False, default="Available")
    detail = Column(Text, nullable=True)
    source = Column(String(128), nullable=False, default="world_state")
    correlation_id = Column(String(128), nullable=True)
    event_id = Column(String(36), nullable=True)
    task_id = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_until = Column(DateTime(timezone=True), nullable=False)

