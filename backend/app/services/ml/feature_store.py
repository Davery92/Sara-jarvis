"""ML feature foundation (Desktop Jarvis Overhaul C1).

Pure SQL aggregation over tables Sara already populates — no LLM calls.
One row per user-day into `ml_feature_daily`, built nightly by
app.tasks.ml.materialize_features (see app/services/daily_rhythm.py for the
sibling pattern this mirrors).
"""
import logging
import uuid
from datetime import date, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Rough app -> category classification for focus-time aggregation. Not
# exhaustive — anything unmatched falls into "other" rather than crashing
# or silently dropping the time.
_APP_CATEGORY_KEYWORDS = {
    "browser": ["chrome", "safari", "firefox", "edge", "arc"],
    "code_editor": ["code", "vscode", "pycharm", "intellij", "xcode", "terminal", "iterm"],
    "communication": ["slack", "mail", "outlook", "messages", "teams", "zoom", "discord"],
    "entertainment": ["spotify", "youtube", "netflix", "steam", "music", "tv"],
    "docs": ["word", "excel", "notion", "obsidian", "pages", "numbers", "docs"],
}


def _categorize_app(app_name: Optional[str]) -> str:
    if not app_name:
        return "other"
    lowered = app_name.lower()
    for category, keywords in _APP_CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


def materialize_features(db: Session, user_id: str, target_date: date) -> Dict[str, Any]:
    """Compute and upsert the ml_feature_daily row for one user-day."""
    features: Dict[str, Any] = {"feature_date": target_date.isoformat(), "day_of_week": target_date.weekday()}

    # --- Desktop focus (C1: focus spans, persisted via ml_persistence_subscriber) ---
    focus_rows = db.execute(text("""
        SELECT app, duration_seconds, start_ts, end_ts
        FROM desktop_focus_span
        WHERE user_id = :user_id AND DATE(start_ts) = :target_date
    """), {"user_id": user_id, "target_date": target_date}).fetchall()

    by_category: Dict[str, int] = {}
    first_activity = None
    last_activity = None
    total_focus = 0
    for row in focus_rows:
        category = _categorize_app(row.app)
        duration = int(row.duration_seconds or 0)
        by_category[category] = by_category.get(category, 0) + duration
        total_focus += duration
        if row.start_ts and (first_activity is None or row.start_ts < first_activity):
            first_activity = row.start_ts
        if row.end_ts and (last_activity is None or row.end_ts > last_activity):
            last_activity = row.end_ts

    features["focus_seconds_by_category"] = by_category
    features["first_desktop_activity_at"] = first_activity
    features["last_desktop_activity_at"] = last_activity
    features["total_focus_seconds"] = total_focus

    # --- Location timeline summary ---
    try:
        location_rows = db.execute(text("""
            SELECT place_id, event_type, COUNT(*) as n
            FROM location_event
            WHERE user_id = :user_id AND DATE(created_at) = :target_date
            GROUP BY place_id, event_type
        """), {"user_id": user_id, "target_date": target_date}).fetchall()
        features["location_summary"] = {
            "distinct_places": len({r.place_id for r in location_rows if r.place_id}),
            "transitions": sum(r.n for r in location_rows if r.event_type in ("enter", "exit")),
        }
    except Exception as e:
        logger.debug(f"location_event aggregation skipped: {e}")
        features["location_summary"] = None

    # --- Sleep/health ---
    try:
        recovery = db.execute(text("""
            SELECT sleep_hours, hrv, heart_rate
            FROM daily_recovery_log
            WHERE user_id = :user_id AND log_date = :target_date
        """), {"user_id": user_id, "target_date": target_date}).fetchone()
        features["sleep_hours"] = recovery.sleep_hours if recovery else None
        features["hrv"] = recovery.hrv if recovery else None
        features["resting_heart_rate"] = recovery.heart_rate if recovery else None
    except Exception as e:
        logger.debug(f"daily_recovery_log aggregation skipped: {e}")

    # --- Workout/food flags ---
    try:
        workout_count = db.execute(text("""
            SELECT COUNT(*) as n FROM workout_log
            WHERE user_id = :user_id AND session_date = :target_date AND skipped = false
        """), {"user_id": user_id, "target_date": target_date}).scalar() or 0
        features["workout_logged"] = workout_count > 0
    except Exception as e:
        logger.debug(f"workout_log aggregation skipped: {e}")
        features["workout_logged"] = False

    try:
        food_agg = db.execute(text("""
            SELECT COUNT(*) as meals, SUM(calories) as total_calories
            FROM food_log
            WHERE user_id = :user_id AND DATE(logged_at) = :target_date
        """), {"user_id": user_id, "target_date": target_date}).fetchone()
        features["meals_logged"] = food_agg.meals if food_agg else 0
        features["total_calories"] = float(food_agg.total_calories) if food_agg and food_agg.total_calories else None
    except Exception as e:
        logger.debug(f"food_log aggregation skipped: {e}")
        features["meals_logged"] = 0

    # --- Calendar load ---
    try:
        calendar_rows = db.execute(text("""
            SELECT start_time, end_time FROM calendar_event
            WHERE user_id = :user_id AND DATE(start_time) = :target_date
        """), {"user_id": user_id, "target_date": target_date}).fetchall()
        features["calendar_event_count"] = len(calendar_rows)
        features["calendar_busy_seconds"] = sum(
            max(0, int((r.end_time - r.start_time).total_seconds())) for r in calendar_rows if r.start_time and r.end_time
        )
    except Exception as e:
        logger.debug(f"calendar_event aggregation skipped: {e}")
        features["calendar_event_count"] = 0
        features["calendar_busy_seconds"] = 0

    # --- Notifications sent/engaged ---
    try:
        notif_agg = db.execute(text("""
            SELECT COUNT(*) as sent, COUNT(*) FILTER (WHERE engaged = true) as engaged
            FROM notification_log
            WHERE user_id = :user_id AND DATE(sent_at) = :target_date AND sent = true
        """), {"user_id": user_id, "target_date": target_date}).fetchone()
        features["notifications_sent"] = notif_agg.sent if notif_agg else 0
        features["notifications_engaged"] = notif_agg.engaged if notif_agg else 0
    except Exception as e:
        logger.debug(f"notification_log aggregation skipped: {e}")
        features["notifications_sent"] = 0
        features["notifications_engaged"] = 0

    # --- Voice interactions ---
    try:
        voice_agg = db.execute(text("""
            SELECT COUNT(*) as interactions, COALESCE(SUM(turns), 0) as turns
            FROM voice_interaction_log
            WHERE user_id = :user_id AND DATE(started_at) = :target_date
        """), {"user_id": user_id, "target_date": target_date}).fetchone()
        features["voice_interactions"] = voice_agg.interactions if voice_agg else 0
        features["voice_turns"] = int(voice_agg.turns) if voice_agg else 0
    except Exception as e:
        logger.debug(f"voice_interaction_log aggregation skipped: {e}")
        features["voice_interactions"] = 0
        features["voice_turns"] = 0

    _upsert_feature_row(db, user_id, target_date, features)
    return features


def _upsert_feature_row(db: Session, user_id: str, target_date: date, features: Dict[str, Any]) -> None:
    import json

    db.execute(text("""
        INSERT INTO ml_feature_daily (
            id, user_id, feature_date, focus_seconds_by_category,
            first_desktop_activity_at, last_desktop_activity_at, total_focus_seconds,
            location_summary, sleep_hours, hrv, resting_heart_rate,
            workout_logged, meals_logged, total_calories,
            calendar_event_count, calendar_busy_seconds,
            notifications_sent, notifications_engaged,
            voice_interactions, voice_turns, day_of_week, computed_at
        ) VALUES (
            :id, :user_id, :feature_date, CAST(:focus_seconds_by_category AS jsonb),
            :first_desktop_activity_at, :last_desktop_activity_at, :total_focus_seconds,
            CAST(:location_summary AS jsonb), :sleep_hours, :hrv, :resting_heart_rate,
            :workout_logged, :meals_logged, :total_calories,
            :calendar_event_count, :calendar_busy_seconds,
            :notifications_sent, :notifications_engaged,
            :voice_interactions, :voice_turns, :day_of_week, NOW()
        )
        ON CONFLICT (user_id, feature_date) DO UPDATE SET
            focus_seconds_by_category = EXCLUDED.focus_seconds_by_category,
            first_desktop_activity_at = EXCLUDED.first_desktop_activity_at,
            last_desktop_activity_at = EXCLUDED.last_desktop_activity_at,
            total_focus_seconds = EXCLUDED.total_focus_seconds,
            location_summary = EXCLUDED.location_summary,
            sleep_hours = EXCLUDED.sleep_hours,
            hrv = EXCLUDED.hrv,
            resting_heart_rate = EXCLUDED.resting_heart_rate,
            workout_logged = EXCLUDED.workout_logged,
            meals_logged = EXCLUDED.meals_logged,
            total_calories = EXCLUDED.total_calories,
            calendar_event_count = EXCLUDED.calendar_event_count,
            calendar_busy_seconds = EXCLUDED.calendar_busy_seconds,
            notifications_sent = EXCLUDED.notifications_sent,
            notifications_engaged = EXCLUDED.notifications_engaged,
            voice_interactions = EXCLUDED.voice_interactions,
            voice_turns = EXCLUDED.voice_turns,
            day_of_week = EXCLUDED.day_of_week,
            computed_at = NOW()
    """), {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "feature_date": target_date,
        "focus_seconds_by_category": json.dumps(features.get("focus_seconds_by_category") or {}),
        "first_desktop_activity_at": features.get("first_desktop_activity_at"),
        "last_desktop_activity_at": features.get("last_desktop_activity_at"),
        "total_focus_seconds": features.get("total_focus_seconds") or 0,
        "location_summary": json.dumps(features.get("location_summary")) if features.get("location_summary") is not None else None,
        "sleep_hours": features.get("sleep_hours"),
        "hrv": features.get("hrv"),
        "resting_heart_rate": features.get("resting_heart_rate"),
        "workout_logged": features.get("workout_logged") or False,
        "meals_logged": features.get("meals_logged") or 0,
        "total_calories": features.get("total_calories"),
        "calendar_event_count": features.get("calendar_event_count") or 0,
        "calendar_busy_seconds": features.get("calendar_busy_seconds") or 0,
        "notifications_sent": features.get("notifications_sent") or 0,
        "notifications_engaged": features.get("notifications_engaged") or 0,
        "voice_interactions": features.get("voice_interactions") or 0,
        "voice_turns": features.get("voice_turns") or 0,
        "day_of_week": features.get("day_of_week"),
    })
    db.commit()


def backfill_features(db: Session, user_id: str, days: int = 30) -> int:
    """One-time/manual backfill for existing history — lets model training
    start with more than a few days of data instead of waiting a month."""
    updated = 0
    today = date.today()
    for offset in range(1, days + 1):
        target_date = today - timedelta(days=offset)
        try:
            materialize_features(db, user_id, target_date)
            updated += 1
        except Exception as e:
            logger.warning(f"backfill_features failed for {target_date}: {e}")
            db.rollback()
    return updated
