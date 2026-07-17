"""Daily Rhythm model: a persistent, queryable model of David's typical day.

One row per (user_id, rhythm_key, day_scope) — wake/sleep windows, work
blocks, gym windows, meal times, home/away rhythm, per-place visit rhythm.
Recomputed nightly (see services/daily_rhythm.py). All times are stored as
ET local times (naive `time` — no tz component; the app.core.timezone
convention is that local wall-clock times are stored without a UTC offset).
"""
from sqlalchemy import Column, String, Integer, Float, Time, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class DailyRhythm(Base):
    """A learned time-of-day pattern for one facet of David's day."""
    __tablename__ = "daily_rhythm"
    __table_args__ = (
        UniqueConstraint("user_id", "rhythm_key", "day_scope", name="uq_daily_rhythm_user_key_scope"),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # wake, bedtime, first_activity, leave_home, return_home, work_start,
    # work_end, gym_window, lunch, dinner, winddown, or 'place:<known_place.id>'
    rhythm_key = Column(String(50), nullable=False)
    day_scope = Column(String(10), nullable=False, default="weekday")  # weekday | weekend | mon..sun

    window_start = Column(Time, nullable=True)  # ET, P20
    window_end = Column(Time, nullable=True)    # ET, P80
    median_time = Column(Time, nullable=True)   # ET

    confidence = Column(Float, nullable=False, default=0.0)  # 0-1, sample size + variance
    sample_count = Column(Integer, nullable=False, default=0)
    variance_minutes = Column(Integer, nullable=True)

    evidence = Column(JSONB, nullable=True)  # last N observations with source tags, for explainability

    computed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<DailyRhythm(key='{self.rhythm_key}', scope='{self.day_scope}', median={self.median_time})>"
