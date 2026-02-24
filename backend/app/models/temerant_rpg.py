"""Separate scene-based Temerant RPG models (independent of habit Temerant)."""

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Integer,
    Float,
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


class TemerantRpgCharacter(Base):
    __tablename__ = "temerant_rpg_character"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), unique=True, nullable=False)
    character_name = Column(Text, nullable=False)
    origin = Column(Text, nullable=True)
    backstory = Column(Text, nullable=True)
    body = Column(Integer, nullable=False, default=3)
    mind = Column(Integer, nullable=False, default=5)
    craft = Column(Integer, nullable=False, default=3)
    voice = Column(Integer, nullable=False, default=2)
    luck = Column(Integer, nullable=False, default=3)
    coin_talents = Column(Float, nullable=False, default=38.0)
    rank = Column(String(32), nullable=False, default="none")
    conditions = Column(JSONB, nullable=False, default=dict)
    skills = Column(JSONB, nullable=False, default=dict)
    inventory = Column(JSONB, nullable=False, default=list)
    term_index = Column(Integer, nullable=False, default=1)
    current_scene_id = Column(String, ForeignKey("temerant_rpg_scene.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class TemerantRpgWorldState(Base):
    __tablename__ = "temerant_rpg_world_state"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_temerant_rpg_world_state_user"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_rpg_character.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    day_slot = Column(String(16), nullable=False, default="afternoon")
    weather = Column(String(64), nullable=False, default="autumn chill")
    location_hint = Column(String(128), nullable=False, default="Imre")
    ambient_events = Column(JSONB, nullable=False, default=list)
    pending_consequences = Column(JSONB, nullable=False, default=list)
    last_advance_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantRpgCharacter", foreign_keys=[character_id])


class TemerantRpgScene(Base):
    __tablename__ = "temerant_rpg_scene"
    __table_args__ = (
        Index("ix_temerant_rpg_scene_user_opened", "user_id", "opened_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_rpg_character.id", ondelete="CASCADE"), nullable=False)
    scene_number = Column(Integer, nullable=False)
    local_date = Column(Date, nullable=False)
    day_slot = Column(String(16), nullable=False)
    location = Column(String(128), nullable=False)
    title = Column(String(180), nullable=False)
    opening_text = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="open")
    summary = Column(Text, nullable=True)
    consequences = Column(JSONB, nullable=False, default=list)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    character = relationship("TemerantRpgCharacter", foreign_keys=[character_id])


class TemerantRpgSceneTurn(Base):
    __tablename__ = "temerant_rpg_scene_turn"
    __table_args__ = (
        Index("ix_temerant_rpg_scene_turn_scene_idx", "scene_id", "turn_index"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey("temerant_rpg_scene.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    turn_index = Column(Integer, nullable=False)
    player_action = Column(Text, nullable=False)
    gm_response = Column(Text, nullable=False)
    resolution = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    scene = relationship("TemerantRpgScene")
    user = relationship("User")


class TemerantRpgRelationship(Base):
    __tablename__ = "temerant_rpg_relationship"
    __table_args__ = (
        UniqueConstraint("character_id", "npc_key", name="uq_temerant_rpg_relationship_character_npc"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_rpg_character.id", ondelete="CASCADE"), nullable=False)
    npc_key = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False)
    disposition = Column(String(24), nullable=False, default="neutral")
    trust = Column(String(24), nullable=False, default="guarded")
    respect = Column(String(24), nullable=False, default="neutral")
    debt_balance = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantRpgCharacter")


class TemerantRpgJournalEntry(Base):
    __tablename__ = "temerant_rpg_journal_entry"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_temerant_rpg_journal_user_date"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_rpg_character.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    summary_markdown = Column(Text, nullable=False)
    scene_ids = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantRpgCharacter")


class TemerantRpgTerm(Base):
    __tablename__ = "temerant_rpg_term"
    __table_args__ = (
        UniqueConstraint("user_id", "term_index", name="uq_temerant_rpg_term_user_index"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String, ForeignKey("temerant_rpg_character.id", ondelete="CASCADE"), nullable=False)
    term_index = Column(Integer, nullable=False)
    month = Column(Date, nullable=False)
    admissions_result = Column(String(24), nullable=False, default="mixed")
    tuition_talents = Column(Float, nullable=False, default=10.0)
    summary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    character = relationship("TemerantRpgCharacter")
