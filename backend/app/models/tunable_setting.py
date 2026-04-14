"""TunableSetting model — editable system knobs read by various subsystems."""
from sqlalchemy import Column, String, Boolean, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class TunableSetting(Base):
    """
    A user-editable knob like a notification cooldown, ACS threshold, or
    morning brief tone. Read at runtime by `app.services.tunables.get_tunable()`
    which caches values for ~60 seconds.

    Use JSONB for value/default/min/max so the same column works for ints,
    floats, strings, booleans, or arbitrary structures.
    """
    __tablename__ = "tunable_setting"
    __table_args__ = {"extend_existing": True}

    key = Column(String(120), primary_key=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, default="general")
    value_type = Column(String(20), nullable=False)  # int | float | string | bool | json
    value = Column(JSONB, nullable=False)
    default_value = Column(JSONB, nullable=False)
    min_value = Column(JSONB, nullable=True)
    max_value = Column(JSONB, nullable=True)
    unit = Column(String(50), nullable=True)
    editable = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
