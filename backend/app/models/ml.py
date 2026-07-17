"""ML feature store + model registry (Desktop Jarvis Overhaul C1/C2)."""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Date, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class DesktopFocusSpan(Base):
    """Durable copy of DESKTOP_FOCUS_SPAN events — these previously only
    flowed transiently through salience/working memory."""
    __tablename__ = "desktop_focus_span"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(String, nullable=True)
    app = Column(String, nullable=True)
    window = Column(String, nullable=True)
    domain = Column(String, nullable=True)
    derived_state = Column(String, nullable=True)
    start_ts = Column(DateTime(timezone=True), nullable=True)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, default=0)
    keyboard_events = Column(Integer, default=0)
    mouse_events = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class VoiceInteractionLog(Base):
    """Durable per-conversation record from the Jetson voice pipeline."""
    __tablename__ = "voice_interaction_log"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    turns = Column(Integer, default=0)
    duration_seconds = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    source = Column(String, default="jetson_voice")


class MLFeatureDaily(Base):
    """One row per user-day of aggregated features for the ML training pipeline."""
    __tablename__ = "ml_feature_daily"
    __table_args__ = (
        UniqueConstraint("user_id", "feature_date", name="uq_ml_feature_daily_user_date"),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    feature_date = Column(Date, nullable=False)

    focus_seconds_by_category = Column(JSONB, nullable=True)
    first_desktop_activity_at = Column(DateTime(timezone=True), nullable=True)
    last_desktop_activity_at = Column(DateTime(timezone=True), nullable=True)
    total_focus_seconds = Column(Integer, default=0)

    location_summary = Column(JSONB, nullable=True)

    sleep_hours = Column(Float, nullable=True)
    hrv = Column(Float, nullable=True)
    resting_heart_rate = Column(Float, nullable=True)

    workout_logged = Column(Boolean, default=False)
    meals_logged = Column(Integer, default=0)
    total_calories = Column(Float, nullable=True)

    calendar_event_count = Column(Integer, default=0)
    calendar_busy_seconds = Column(Integer, default=0)

    notifications_sent = Column(Integer, default=0)
    notifications_engaged = Column(Integer, default=0)

    voice_interactions = Column(Integer, default=0)
    voice_turns = Column(Integer, default=0)

    day_of_week = Column(Integer, nullable=True)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())


class MLNotificationOutcome(Base):
    """Per-notification features-at-send-time + eventual outcome."""
    __tablename__ = "ml_notification_outcome"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    notification_log_id = Column(String, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=False)
    hour = Column(Integer, nullable=True)
    day_of_week = Column(Integer, nullable=True)
    activity_state = Column(String, nullable=True)
    interruptibility_score = Column(Float, nullable=True)
    device = Column(String, nullable=True)
    category = Column(String, nullable=True)
    location = Column(String, nullable=True)
    outcome = Column(String, nullable=True)  # opened|acted|dismissed|ignored
    outcome_latency_seconds = Column(Float, nullable=True)
    features = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MLPredictionLog(Base):
    """Every shadow/live model inference, for later evaluation against ground truth."""
    __tablename__ = "ml_prediction_log"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    model_family = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    features_hash = Column(String, nullable=True)
    features = Column(JSONB, nullable=True)
    prediction = Column(JSONB, nullable=True)
    ground_truth = Column(JSONB, nullable=True)
    mode = Column(String, default="shadow")  # shadow|live
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MLModelVersion(Base):
    """Model registry — family, version, artifact location, metrics, status."""
    __tablename__ = "ml_model_version"
    __table_args__ = (
        UniqueConstraint("family", "version", name="uq_ml_model_version_family_version"),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    family = Column(String, nullable=False)
    version = Column(String, nullable=False)
    artifact_key = Column(String, nullable=True)
    metrics = Column(JSONB, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    status = Column(String, default="candidate")  # candidate|shadow|active|retired
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    activated_at = Column(DateTime(timezone=True), nullable=True)
