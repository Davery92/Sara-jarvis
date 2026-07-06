"""
Predictive Engine — pattern-based predictions for upcoming activities.

Analyzes behavioral patterns and calendar to generate forward-looking suggestions:
  "You usually go to the gym on Thursdays"

Runs as a Celery task every 30 minutes during waking hours.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


async def generate_predictions(user_id: str) -> List[Dict[str, Any]]:
    """
    Generate predictions for the next 24 hours based on behavioral patterns.

    Returns list of predictions with title, message, confidence, and suggested action.
    """
    from app.db.session import get_async_session_factory
    from sqlalchemy import text
    from app.core.timezone import now as local_now

    async_session = get_async_session_factory()
    predictions = []
    now = local_now()
    today_name = now.strftime("%A").lower()
    current_hour = now.hour

    # Only generate during waking hours (7am - 10pm)
    if current_hour < 7 or current_hour > 22:
        return predictions

    # C3: next_block model — replaces the SQL heuristics below once trained
    # with confidence >= threshold. No model exists yet (no supervised
    # activity-vocabulary label source), so this is a no-op today — kept
    # here so promotion is a data problem, not a wiring problem.
    try:
        from app.services.ml import inference as ml_inference
        next_block = ml_inference.predict_multiclass(
            "next_block",
            {"hour": current_hour, "day_of_week": now.weekday()},
            user_id=user_id,
        )
        if next_block:
            label, confidence, version = next_block
            if confidence >= 0.65:
                predictions.append({
                    "type": "next_block_prediction",
                    "title": "Coming up",
                    "message": f"You're likely to be doing: {label}",
                    "confidence": confidence,
                    "priority": "low",
                    "source": f"ml:next_block@{version}",
                })
    except Exception as e:
        logger.debug(f"next_block prediction skipped: {e}")

    async with async_session() as db:
        # 1. Day-of-week habit patterns from calendar history
        try:
            result = await db.execute(text("""
                SELECT title, start_time,
                       COUNT(*) as occurrences
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time > NOW() - INTERVAL '90 days'
                  AND EXTRACT(DOW FROM start_time) = EXTRACT(DOW FROM NOW())
                  AND source != 'sara'
                GROUP BY title, EXTRACT(HOUR FROM start_time), start_time
                HAVING COUNT(*) >= 3
                ORDER BY occurrences DESC
                LIMIT 5
            """), {"uid": user_id})
            recurring = result.fetchall()

            for row in recurring:
                title, start_time, count = row
                event_hour = start_time.hour if start_time else 0
                # Only predict if the event hasn't happened yet today
                if event_hour > current_hour:
                    predictions.append({
                        "type": "routine_prediction",
                        "title": f"Usual {today_name} activity",
                        "message": f"You typically have \"{title}\" on {today_name}s around {event_hour}:00 ({count} times in 90 days).",
                        "confidence": min(0.9, 0.4 + count * 0.1),
                        "priority": "low",
                        "predicted_time": f"{event_hour}:00",
                    })
        except Exception as e:
            logger.debug(f"Calendar pattern prediction failed: {e}")

        # 2. Check for upcoming events that need prep but don't have it
        try:
            result = await db.execute(text("""
                SELECT id, title, start_time, description
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time BETWEEN NOW() + INTERVAL '2 hours' AND NOW() + INTERVAL '6 hours'
                  AND is_completed = FALSE
                ORDER BY start_time ASC
                LIMIT 3
            """), {"uid": user_id})
            upcoming = result.fetchall()

            for row in upcoming:
                event_id, title, start_time, desc = row
                hours_until = (start_time.replace(tzinfo=None) - datetime.now(timezone.utc)).total_seconds() / 3600
                if desc and len(desc) > 20:
                    predictions.append({
                        "type": "preparation_needed",
                        "title": f"Prepare for: {title}",
                        "message": f"\"{title}\" is in {hours_until:.0f} hours. You might want to review your notes or prep.",
                        "confidence": 0.7,
                        "priority": "normal",
                    })
        except Exception as e:
            logger.debug(f"Event prep prediction failed: {e}")

        # 3. Weather awareness for outdoor events in next 6 hours
        try:
            result = await db.execute(text("""
                SELECT title, start_time
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time BETWEEN NOW() AND NOW() + INTERVAL '6 hours'
                  AND is_completed = FALSE
                ORDER BY start_time ASC
            """), {"uid": user_id})
            upcoming_events = result.fetchall()

            outdoor_keywords = ["walk", "run", "hike", "park", "outdoor", "bbq", "picnic", "golf", "tennis", "soccer", "football", "garden"]
            for row in upcoming_events:
                title, start_time = row
                if any(kw in (title or "").lower() for kw in outdoor_keywords):
                    # Check weather from working memory
                    try:
                        from app.services.working_memory import get_memory
                        wm = await get_memory(user_id)
                        weather = wm.get("weather_condition", "")
                        temp_outside = wm.get("temperature_outside")
                        if weather and any(w in weather.lower() for w in ["rain", "storm", "snow", "thunder"]):
                            predictions.append({
                                "type": "weather_alert",
                                "title": f"Weather alert for: {title}",
                                "message": f"Weather is \"{weather}\" — you have \"{title}\" coming up. Consider an indoor alternative or bring gear.",
                                "confidence": 0.8,
                                "priority": "normal",
                            })
                        elif temp_outside is not None and (temp_outside > 95 or temp_outside < 25):
                            predictions.append({
                                "type": "weather_alert",
                                "title": f"Temperature alert for: {title}",
                                "message": f"It's {temp_outside}°F outside — dress accordingly for \"{title}\".",
                                "confidence": 0.7,
                                "priority": "low",
                            })
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Weather/outdoor prediction failed: {e}")

        # 4. Travel time predictions for events with locations
        try:
            result = await db.execute(text("""
                SELECT title, start_time, location
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time BETWEEN NOW() + INTERVAL '30 minutes' AND NOW() + INTERVAL '3 hours'
                  AND is_completed = FALSE
                  AND location IS NOT NULL AND location != ''
                ORDER BY start_time ASC
                LIMIT 2
            """), {"uid": user_id})
            travel_events = result.fetchall()

            for row in travel_events:
                title, start_time, location = row
                hours_until = (start_time.replace(tzinfo=None) - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_until < 1.5:
                    predictions.append({
                        "type": "travel_reminder",
                        "title": f"Time to leave for: {title}",
                        "message": f"\"{title}\" at {location} starts in {hours_until:.0f}h. You may want to start heading out.",
                        "confidence": 0.65,
                        "priority": "normal",
                    })
        except Exception as e:
            logger.debug(f"Travel prediction failed: {e}")

        # 5. High-confidence learned behavioral patterns whose usual time is
        # approaching. Capped to 1/tick and skips patterns morning_proactive_service
        # already suggested in the last 24h, so the two pattern-driven surfacing
        # paths don't double-nag about the same thing.
        try:
            result = await db.execute(text("""
                SELECT description, trigger_conditions, confidence
                FROM behavioral_pattern
                WHERE user_id = :uid
                  AND status IN ('active', 'confirmed')
                  AND confidence >= 0.8
                  AND trigger_type = 'time'
                  AND (last_suggested_at IS NULL OR last_suggested_at < NOW() - INTERVAL '24 hours')
            """), {"uid": user_id})
            patterns = result.fetchall()

            now_minutes = current_hour * 60 + now.minute
            best = None
            for description, trigger_conditions, confidence in patterns:
                pattern_time = (trigger_conditions or {}).get("time")
                if not pattern_time:
                    continue
                try:
                    p_hour, p_minute = (int(x) for x in pattern_time.split(":")[:2])
                except (ValueError, AttributeError):
                    continue
                minutes_until = (p_hour * 60 + p_minute) - now_minutes
                if 0 < minutes_until <= 45 and (best is None or minutes_until < best[0]):
                    best = (minutes_until, description, confidence)

            if best:
                minutes_until, description, confidence = best
                predictions.append({
                    "type": "learned_pattern",
                    "title": "Usual pattern coming up",
                    "message": f"{description} — usually around this time (learned pattern, {confidence:.0%} confidence).",
                    "confidence": min(0.85, confidence),
                    "priority": "low",
                })
        except Exception as e:
            logger.debug(f"Behavioral pattern prediction failed: {e}")

        # 6. Daily Rhythm windows opening soon (wake/gym/meal/winddown/bedtime).
        try:
            import asyncio
            from app.services.daily_rhythm import get_upcoming_rhythm_window

            def _fetch_sync():
                from app.db.base import SessionLocal
                sdb = SessionLocal()
                try:
                    return get_upcoming_rhythm_window(sdb, user_id, now=now, within_minutes=45)
                finally:
                    sdb.close()

            upcoming = await asyncio.to_thread(_fetch_sync)
            if upcoming:
                predictions.append({
                    "type": "rhythm_window",
                    "title": "Rhythm window opening",
                    "message": (
                        f"Your {upcoming['label']} is usually in about {upcoming['minutes_until']} min "
                        f"({upcoming['confidence']:.0%} confidence, learned rhythm)."
                    ),
                    "confidence": min(0.75, upcoming["confidence"]),
                    "priority": "low",
                })
        except Exception as e:
            logger.debug(f"Rhythm window prediction failed: {e}")

    return predictions[:6]  # Max 6 predictions per check


async def send_predictions(user_id: str):
    """Generate predictions and send high-confidence ones as notifications."""
    from app.services.unified_notification import send_notification

    predictions = await generate_predictions(user_id)

    for pred in predictions:
        if pred["confidence"] >= 0.6:
            await send_notification(
                user_id=user_id,
                title=pred["title"],
                message=pred["message"],
                priority=pred.get("priority", "low"),
                category="checkin",
                topic=f"prediction:{hash(pred['title']) % 100000}",
                source=pred.get("source", "predictive_engine"),
            )

    # Inject predictions into daily brief context layer
    if predictions:
        try:
            from app.services.daily_brief.context_layer import ContextLayer
            context_layer = ContextLayer()
            await context_layer.inject_predictions(user_id)
        except Exception as e:
            logger.debug(f"Brief prediction injection failed: {e}")

        logger.info(f"Predictive engine: generated {len(predictions)} predictions, sent {sum(1 for p in predictions if p['confidence'] >= 0.6)}")
