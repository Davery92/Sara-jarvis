"""External workout — workouts ingested from Apple Health / other sources.

Distinct from workout_sessions/workout_log (those are David's manually-logged
strength sessions). external_workout holds Apple-Watch tracked runs, walks,
yoga, etc. so the two streams don't get mixed.
"""
import uuid
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class ExternalWorkout(Base):
    __tablename__ = "external_workout"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="ix_external_workout_dedup"),
        Index("ix_external_workout_user_started", "user_id", "started_at"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    source = Column(String(50), nullable=False, default="apple_health")
    external_id = Column(String(128), nullable=False)

    activity_type = Column(String(80), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    duration_seconds = Column(Integer, nullable=False)

    total_energy_kcal = Column(Numeric(10, 2))
    total_distance_m = Column(Numeric(12, 2))

    avg_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    min_heart_rate = Column(Integer)
    hr_zones = Column(JSONB)
    workout_metadata = Column(JSONB)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
