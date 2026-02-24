"""Temerant RPG system models."""

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Integer,
    Float,
    Boolean,
    Date,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
import uuid


class TemerantCharacter(Base):
    __tablename__ = "temerant_character"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), unique=True, nullable=False)
    character_name = Column(Text, nullable=False)
    backstory = Column(Text, nullable=True)
    origin = Column(Text, nullable=True)
    current_rank = Column(String(32), nullable=False, default="elir")
    coin_balance = Column(Float, nullable=False, default=0.0)
    alar_strength = Column(Integer, nullable=False, default=0)
    naming_affinity = Column(Integer, nullable=False, default=0)
    specialization_track = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class TemerantAttributeState(Base):
    __tablename__ = "temerant_attribute_state"
    __table_args__ = (
        UniqueConstraint("character_id", "attribute", name="uq_temerant_attribute_state_character_attr"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    attribute = Column(String(32), nullable=False)
    xp_total = Column(Integer, nullable=False, default=0)
    xp_term = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    character = relationship("TemerantCharacter")


class TemerantLedgerEntry(Base):
    __tablename__ = "temerant_xp_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_temerant_ledger_idempotency"),
        Index("ix_temerant_ledger_user_date", "user_id", "local_date"),
        Index("ix_temerant_ledger_character_attr_time", "character_id", "attribute", "occurred_at"),
        Index("ix_temerant_ledger_source", "source_type", "source_ref_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(64), nullable=False)
    source_ref_id = Column(String(255), nullable=True)
    idempotency_key = Column(String(255), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    local_date = Column(Date, nullable=False)
    attribute = Column(String(32), nullable=False)
    subdomain = Column(String(64), nullable=True)
    xp_delta = Column(Integer, nullable=False, default=0)
    coin_delta = Column(Float, nullable=False, default=0.0)
    name_delta = Column(Integer, nullable=False, default=0)
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    character = relationship("TemerantCharacter")


class TemerantDailyState(Base):
    __tablename__ = "temerant_daily_state"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_temerant_daily_state_user_date"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    categories_completed = Column(Integer, nullable=False, default=0)
    body_xp = Column(Integer, nullable=False, default=0)
    mind_xp = Column(Integer, nullable=False, default=0)
    craft_xp = Column(Integer, nullable=False, default=0)
    coin_xp = Column(Integer, nullable=False, default=0)
    name_xp = Column(Integer, nullable=False, default=0)
    oracle_roll_raw = Column(Integer, nullable=True)
    oracle_roll_modified = Column(Integer, nullable=True)
    oracle_event_id = Column(String, ForeignKey("temerant_oracle_event.id", ondelete="SET NULL"), nullable=True)
    term_month = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantCharacter")


class TemerantStoryThread(Base):
    __tablename__ = "temerant_story_thread"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="open")
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantCharacter")


class TemerantOracleEvent(Base):
    __tablename__ = "temerant_oracle_event"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(String, ForeignKey("temerant_story_thread.id", ondelete="SET NULL"), nullable=True)
    local_date = Column(Date, nullable=False)
    tier = Column(String(16), nullable=False)
    category = Column(String(32), nullable=False)
    title = Column(Text, nullable=False)
    hook = Column(Text, nullable=False)
    stakes = Column(Text, nullable=True)
    options = Column(JSONB, nullable=True)
    resolution = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="open")
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    character = relationship("TemerantCharacter")
    thread = relationship("TemerantStoryThread")


class TemerantTerm(Base):
    __tablename__ = "temerant_term"
    __table_args__ = (
        UniqueConstraint("user_id", "term_month", name="uq_temerant_term_user_month"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    term_month = Column(Date, nullable=False)
    completion_pct = Column(Float, nullable=False, default=0.0)
    admissions_result = Column(String(16), nullable=False, default="good")
    tuition_talents = Column(Integer, nullable=False, default=10)
    xp_multiplier = Column(Float, nullable=False, default=1.0)
    coin_delta = Column(Float, nullable=False, default=0.0)
    review_markdown = Column(Text, nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantCharacter")


class TemerantMasterwork(Base):
    __tablename__ = "temerant_masterwork"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="planned")
    evidence = Column(JSONB, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantCharacter")


class TemerantMappingRule(Base):
    __tablename__ = "temerant_mapping_rule"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source_kind = Column(String(64), nullable=False)
    source_ref = Column(String(255), nullable=True)
    target_attribute = Column(String(32), nullable=False)
    target_subdomain = Column(String(64), nullable=True)
    xp_base = Column(Integer, nullable=False, default=1)
    bonus_rules = Column(JSONB, nullable=False, default=dict)
    daily_cap = Column(Integer, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class TemerantJournalEntry(Base):
    __tablename__ = "temerant_journal_entry"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_temerant_journal_user_date"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_character.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    summary_structured = Column(JSONB, nullable=False, default=dict)
    summary_markdown = Column(Text, nullable=False)
    source_event_count = Column(Integer, nullable=False, default=0)
    generated_by = Column(String(32), nullable=False, default="rules")
    model = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantCharacter")


class TemerantIngestionCursor(Base):
    __tablename__ = "temerant_ingestion_cursor"
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", name="uq_temerant_ingestion_cursor_user_source"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(64), nullable=False)
    cursor_value = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")

