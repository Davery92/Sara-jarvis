from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Boolean, JSON, Float, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class FitnessProfile(Base):
    __tablename__ = "fitness_profile"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    demographics = Column(JSON, nullable=True)  # age, sex, height, weight, bodyfat?
    equipment = Column(JSON, nullable=True)     # list of equipment available
    preferences = Column(JSON, nullable=True)   # style, dislikes, session length
    constraints = Column(JSON, nullable=True)   # days/week, no-go times, injuries
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FitnessGoal(Base):
    __tablename__ = "fitness_goal"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    goal_type = Column(String, nullable=False)  # fat_loss, hypertrophy, strength, endurance, etc.
    targets = Column(JSON, nullable=True)
    timeframe = Column(String, nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FitnessPlan(Base):
    __tablename__ = "fitness_plan"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    meta = Column(JSON, nullable=True)  # phases, days/week, time-caps
    status = Column(String, default="draft")  # draft, active, archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Workout(Base):
    __tablename__ = "workout"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(String, ForeignKey("fitness_plan.id", ondelete="CASCADE"), nullable=True)
    title = Column(String, nullable=False)
    phase = Column(String, nullable=True)
    week = Column(Integer, nullable=True)
    day_of_week = Column(Integer, nullable=True)  # 0=Mon .. 6=Sun
    duration_min = Column(Integer, nullable=True)
    prescription = Column(JSON, nullable=True)  # blocks/exercises/sets×reps/intensity/RPE/rest
    status = Column(String, default="scheduled")  # scheduled, completed, skipped, floating
    calendar_event_id = Column(String, ForeignKey("event.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    plan = relationship("FitnessPlan")


class WorkoutLog(Base):
    __tablename__ = "workout_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workout_id = Column(String, ForeignKey("workout.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    exercise_id = Column(String, nullable=True)  # logical exercise identifier from prescription
    set_index = Column(Integer, nullable=False)
    weight = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    rpe = Column(Integer, nullable=True)
    notes = Column(Text, default="")
    flags = Column(JSON, nullable=True)  # pain, form issues, time pressure
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MorningReadiness(Base):
    __tablename__ = "morning_readiness"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    hrv_ms = Column(Integer, nullable=True)
    rhr = Column(Integer, nullable=True)
    sleep_hours = Column(Integer, nullable=True)
    energy = Column(Integer, nullable=False)
    soreness = Column(Integer, nullable=False)
    stress = Column(Integer, nullable=False)
    time_available_min = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    recommendation = Column(String, nullable=False)  # keep|reduce|swap|move
    adjustments = Column(JSON, nullable=True)
    message = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FitnessIdempotency(Base):
    __tablename__ = "fitness_idempotency"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    client_txn_id = Column(String, nullable=False, index=True)
    hash = Column(String, nullable=True)
    applied_at = Column(DateTime(timezone=True), server_default=func.now())
    succeeded = Column(Boolean, default=True)


class ExerciseLibrary(Base):
    __tablename__ = "exercise_library"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    movement_pattern = Column(String, nullable=False, index=True)
    muscle_groups = Column(JSON, nullable=True)
    equipment_required = Column(JSON, nullable=True)
    equipment_alternatives = Column(JSON, nullable=True)
    difficulty_level = Column(Integer, nullable=True)
    injury_contraindications = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    instructions = Column(JSON, nullable=True)
    substitutions = Column(JSON, nullable=True)
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MovementPattern(Base):
    __tablename__ = "movement_patterns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pattern_name = Column(String, nullable=False, unique=True)
    pattern_type = Column(String, nullable=False)
    primary_muscles = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    progression_hierarchy = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReadinessAdjustment(Base):
    __tablename__ = "readiness_adjustments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    readiness_id = Column(String, ForeignKey("morning_readiness.id", ondelete="CASCADE"), nullable=False)
    workout_id = Column(String, ForeignKey("workout.id", ondelete="CASCADE"), nullable=False)
    adjustment_type = Column(String, nullable=False)
    original_prescription = Column(JSON, nullable=True)
    adjusted_prescription = Column(JSON, nullable=True)
    reasoning = Column(Text, nullable=True)
    applied_at = Column(DateTime(timezone=True), server_default=func.now())

    readiness = relationship("MorningReadiness", backref="readiness_adjustments_list")
    workout = relationship("Workout", backref="readiness_adjustments")


class PlanTemplate(Base):
    __tablename__ = "plan_templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    template_type = Column(String, nullable=False)
    days_per_week = Column(Integer, nullable=False)
    weeks_per_phase = Column(Integer, nullable=True)
    phases = Column(JSON, nullable=False)
    equipment_required = Column(JSON, nullable=True)
    difficulty_level = Column(Integer, nullable=True)
    primary_goals = Column(JSON, nullable=True)
    workout_templates = Column(JSON, nullable=False)
    substitution_rules = Column(JSON, nullable=True)
    progression_rules = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReadinessBaseline(Base):
    __tablename__ = "readiness_baselines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True)
    hrv_baseline = Column(Float, nullable=True)
    hrv_std_dev = Column(Float, nullable=True)
    rhr_baseline = Column(Float, nullable=True)
    rhr_std_dev = Column(Float, nullable=True)
    sleep_baseline = Column(Float, nullable=True)
    baseline_period_days = Column(Integer, default=14, nullable=True)
    last_calculated = Column(DateTime, nullable=True)
    sample_count = Column(Integer, default=0, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workout_id = Column(String, ForeignKey("workout.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, nullable=False)
    session_state = Column(String, nullable=False, default="idle")
    current_block_index = Column(Integer, default=0, nullable=True)
    current_exercise_index = Column(Integer, default=0, nullable=True)
    current_set_index = Column(Integer, default=0, nullable=True)
    rest_timer_ends_at = Column(DateTime, nullable=True)
    session_data = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workout = relationship("Workout", backref="sessions")

    __table_args__ = (
        Index('ix_workout_sessions_workout_active', 'workout_id', 'session_state'),
    )


class FitnessEvent(Base):
    __tablename__ = "fitness_event"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    location = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    status = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
