"""
Sara Status & Brief Endpoints

Exposes Sara's current internal state: emotional state, recent thoughts,
pending observations, David's energy level, and PKG stats.

Also provides the /api/sara/brief endpoint for the unified Sara screen
with time-adaptive contextual data.
"""

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sara-status"])


def _extract_latest_thought(content: Optional[str]) -> str:
    """Extract a clean, human-readable thought line from raw journal content."""
    raw = (content or "").strip()
    if not raw:
        return "Keeping an eye on things."

    thought = re.split(r'\*{0,2}HANDOFF:?\*{0,2}', raw, flags=re.IGNORECASE)[0].strip()
    thought = re.sub(r'```.*?```', '', thought, flags=re.DOTALL)
    thought = re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', thought)
    thought = re.sub(r'#{1,3}\s*', '', thought)
    thought = re.sub(r'`[^`]+`', '', thought)
    thought = re.sub(r'\(topic\s+\S+\)', '', thought)
    thought = re.sub(r'^\s*[\{\[].*[\}\]]\s*$', '', thought, flags=re.MULTILINE)
    thought = re.sub(r'\{[^}]{20,}\}', '', thought)

    lines = []
    for line in thought.split('\n'):
        clean = line.strip('- ').strip()
        if not clean:
            continue
        if re.match(r'^(Summary of actions|Actions taken|Status|Checked|Confirmed):?\s*$', clean, re.IGNORECASE):
            continue
        if clean.startswith('{') and clean.endswith('}'):
            continue
        lines.append(clean)

    notable = [l for l in lines if not re.match(r'^(Checked|Confirmed|Verified|Queried|Retrieved)\b', l)]
    text = ' '.join((notable or lines)[:2]).strip()
    text = re.sub(r'\s+([.,!?])', r'\1', text)
    text = re.sub(r'\s{2,}', ' ', text)

    if len(text) > 250:
        cut = text[:250].rfind('.')
        if cut > 40:
            text = text[:cut + 1]
        else:
            text = text[:250].rsplit(' ', 1)[0] + '...'

    return text or "Keeping an eye on things."


def _extract_watching_for(content: Optional[str]) -> List[str]:
    """Return concise 'watching for' items as a list, never raw text blobs."""
    raw = (content or "").strip()
    if not raw:
        return []

    items: List[str] = []
    for line in raw.split('\n'):
        if not any(w in line.lower() for w in ["watching", "looking for", "keeping an eye"]):
            continue
        cleaned = re.sub(r'\*{1,2}', '', line).strip('- ').strip()
        cleaned = re.sub(r'^\s*[\{\[].*[\}\]]\s*$', '', cleaned)
        if cleaned and cleaned not in items:
            items.append(cleaned)
        if len(items) >= 3:
            break
    return items


def _local_day_bounds_naive(now_utc: datetime) -> tuple[datetime, datetime]:
    """Build start/end-of-day bounds in local timezone for naive DB timestamps."""
    local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
    local_now = now_utc.astimezone(local_tz)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    return local_start.replace(tzinfo=None), local_end.replace(tzinfo=None)


def _calendar_source_label(source: Optional[str], ios_calendar_name: Optional[str]) -> str:
    if source == "ios_calendar":
        return ios_calendar_name or "iOS Calendar"
    if source == "sara":
        return "Sara"
    if source:
        return source.replace("_", " ").title()
    return "Calendar"


@router.get("/api/sara/status")
async def get_sara_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get Sara's current internal state for the status indicator.
    Aggregates data from subconscious_state, sara_journal, and agent_run_log.
    """
    user_id = str(current_user.id)
    now = datetime.now(timezone.utc)

    result = {
        "emotional_state": "neutral",
        "watching_for": [],
        "latest_thought": None,
        "last_action": None,
        "pending_observations": 0,
        "hours_since_last_chat": None,
        "pkg_facts_count": 0,
    }

    try:
        # Get latest journal entry for emotional state and thoughts
        journal = db.execute(text("""
            SELECT content, emotional_state, entry_type, created_at
            FROM sara_journal
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 1
        """), {"uid": user_id}).fetchone()

        if journal:
            result["emotional_state"] = journal.emotional_state or "curious"
            content = journal.content or ""
            result["latest_thought"] = _extract_latest_thought(content)
            result["watching_for"] = _extract_watching_for(content)

        # Get latest agent_run_log for last action
        agent_run = db.execute(text("""
            SELECT context_summary, actions_taken, created_at
            FROM agent_run_log
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 1
        """), {"uid": user_id}).fetchone()

        if agent_run and agent_run.actions_taken:
            actions = agent_run.actions_taken
            if isinstance(actions, list) and actions:
                result["last_action"] = _summarize_actions(actions)
            elif isinstance(actions, str):
                result["last_action"] = actions.strip()
            else:
                result["last_action"] = None

        # Get pending observations (unread journal entries of type heartbeat/periodic in last 4 hours)
        four_hours_ago = now - timedelta(hours=4)
        obs_count = db.execute(text("""
            SELECT COUNT(*) as cnt
            FROM sara_journal
            WHERE user_id = :uid
            AND entry_type IN ('heartbeat', 'periodic', 'unified', 'deliberation', 'consolidation')
            AND created_at >= :since
        """), {"uid": user_id, "since": four_hours_ago}).fetchone()

        if obs_count:
            result["pending_observations"] = obs_count.cnt

        # Get subconscious state for David's energy/mood and hours since last chat
        subconscious = db.execute(text("""
            SELECT inferred_energy_level, inferred_mood, hours_since_presence,
                   updated_at
            FROM subconscious_state
            WHERE user_id = :uid
        """), {"uid": user_id}).fetchone()

        if subconscious:
            result["hours_since_last_chat"] = subconscious.hours_since_presence

        # Get PKG facts count
        try:
            from app.services.personal_knowledge_graph import personal_kg
            stats = personal_kg.get_stats()
            result["pkg_facts_count"] = stats.get("total", 0)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Sara status endpoint error: {e}")
        # Return partial result rather than failing
        result["error"] = str(e)

    return result


def _summarize_actions(actions: list) -> Optional[str]:
    """Convert raw tool-call dicts into a human-readable summary."""
    parts = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        tool = a.get("tool", "")
        result = a.get("result", {}) if isinstance(a.get("result"), dict) else {}
        if tool == "check_emails":
            count = result.get("count", 0)
            parts.append("Checked emails" + (f" — {count} need attention" if count else ""))
        elif tool == "check_reminders":
            overdue = result.get("overdue_count", 0)
            parts.append("Checked reminders" + (f" — {overdue} overdue" if overdue else ""))
        elif tool == "check_background_tasks":
            parts.append("Checked background tasks")
        elif tool == "check_weather":
            parts.append("Checked weather")
        elif tool == "check_calendar":
            parts.append("Checked calendar")
        elif tool == "check_learning_reviews":
            parts.append("Checked learning reviews")
        elif tool == "send_notification":
            msg = a.get("args", {}).get("message", "") if isinstance(a.get("args"), dict) else ""
            parts.append("Sent a notification" + (f": {msg[:60]}" if msg else ""))
        elif tool == "send_checkin":
            parts.append("Sent a check-in")
        elif tool:
            # Generic fallback — tool name only, no raw JSON
            parts.append(tool.replace("_", " ").capitalize())
    return "; ".join(parts) if parts else None


def _get_time_period() -> str:
    """Return current time period: morning, afternoon, evening, night."""
    hour = datetime.now().hour
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 22:
        return "evening"
    return "night"


def _get_greeting(time_period: str) -> str:
    """Return a time-appropriate greeting."""
    greetings = {
        "morning": "Good morning, David",
        "afternoon": "Good afternoon, David",
        "evening": "Good evening, David",
        "night": "Hey David",
    }
    return greetings.get(time_period, "Hey David")


@router.get("/api/sara/brief")
async def get_sara_brief(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get Sara's contextual brief for the unified Sara screen.
    Returns time-adaptive sections: weather, calendar, fitness, threads, learning.
    """
    user_id = str(current_user.id)
    now = datetime.now(timezone.utc)
    time_period = _get_time_period()

    result: Dict[str, Any] = {
        "greeting": _get_greeting(time_period),
        "time_period": time_period,
        "activity_state": "unknown",
        "interruptibility": 1.0,
        "brief_sections": [],
        "suggested_actions": [],
        "sara_status": {
            "emotional_state": "neutral",
            "latest_thought": None,
            "watching_for": None,
        },
    }

    try:
        # --- Sara status ---
        journal = db.execute(text("""
            SELECT content, emotional_state FROM sara_journal
            WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id}).fetchone()
        if journal:
            result["sara_status"]["emotional_state"] = journal.emotional_state or "curious"
            raw = journal.content or ""
            result["sara_status"]["latest_thought"] = _extract_latest_thought(raw)
            result["sara_status"]["watching_for"] = _extract_watching_for(raw)

        # --- Activity state + interruptibility ---
        try:
            from app.services.activity_state_machine import activity_state_machine
            from app.services.interruptibility import compute_interruptibility

            snapshot = activity_state_machine.current
            result["activity_state"] = snapshot.state.value
            score = compute_interruptibility(snapshot)
            result["interruptibility"] = score.score
        except Exception:
            pass

        # --- Calendar section ---
        try:
            today_start, today_end = _local_day_bounds_naive(now)
            events = db.execute(text("""
                SELECT id, title, start_time, end_time, all_day, source, ios_calendar_name
                FROM calendar_event
                WHERE user_id = :uid
                AND start_time < :day_end
                AND end_time >= :day_start
                ORDER BY start_time
                LIMIT 5
            """), {"uid": user_id, "day_start": today_start, "day_end": today_end}).fetchall()

            if events:
                event_items = []
                next_in_minutes = None
                for ev in events:
                    event_items.append({
                        "title": ev.title,
                        "start_time": ev.start_time.isoformat() if ev.start_time else "",
                        "end_time": ev.end_time.isoformat() if ev.end_time else "",
                        "all_day": ev.all_day,
                        "source": ev.source,
                        "calendar_label": _calendar_source_label(ev.source, ev.ios_calendar_name),
                    })
                    if next_in_minutes is None and ev.start_time:
                        local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
                        ev_start_aware = ev.start_time.replace(tzinfo=local_tz)
                        if ev_start_aware > now:
                            delta = (ev_start_aware - now).total_seconds() / 60
                            next_in_minutes = int(delta)

                result["brief_sections"].append({
                    "type": "calendar",
                    "data": {
                        "events": event_items,
                        "count": len(event_items),
                        "next_in_minutes": next_in_minutes,
                    },
                })
        except Exception as e:
            logger.debug(f"Brief calendar section failed: {e}")

        # --- Fitness/nutrition section ---
        try:
            today_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
            food_stats = db.execute(text("""
                SELECT COALESCE(SUM(calories), 0) as cal,
                       COALESCE(SUM(protein), 0) as pro,
                       MAX(logged_at) as last_meal
                FROM food_logs
                WHERE user_id = :uid AND logged_at >= :start
            """), {"uid": user_id, "start": today_start_local}).fetchone()

            if food_stats:
                last_meal_ago = None
                if food_stats.last_meal:
                    try:
                        last_meal_time = food_stats.last_meal
                        if hasattr(last_meal_time, 'replace'):
                            delta = (now - last_meal_time.replace(tzinfo=timezone.utc)).total_seconds() / 3600
                            last_meal_ago = round(delta, 1)
                    except Exception:
                        pass

                result["brief_sections"].append({
                    "type": "fitness",
                    "data": {
                        "calories_today": int(food_stats.cal or 0),
                        "protein_today": int(food_stats.pro or 0),
                        "goal": 2200,
                        "last_meal_ago_hours": last_meal_ago,
                    },
                })
        except Exception as e:
            logger.debug(f"Brief fitness section failed: {e}")

        # --- Open threads section ---
        try:
            threads = db.execute(text("""
                SELECT topic, status FROM followup_thread
                WHERE user_id = :uid AND status = 'open'
                ORDER BY updated_at DESC LIMIT 3
            """), {"uid": user_id}).fetchall()

            if threads:
                result["brief_sections"].append({
                    "type": "threads",
                    "data": {
                        "open": len(threads),
                        "topics": [t.topic for t in threads if t.topic],
                    },
                })
        except Exception as e:
            logger.debug(f"Brief threads section failed: {e}")

        # --- Learning section ---
        try:
            reviews = db.execute(text("""
                SELECT COUNT(*) as cnt FROM learning_progress
                WHERE user_id = :uid AND next_review_at <= :now
            """), {"uid": user_id, "now": now}).fetchone()

            if reviews and reviews.cnt > 0:
                result["brief_sections"].append({
                    "type": "learning",
                    "data": {
                        "reviews_due": reviews.cnt,
                    },
                })
        except Exception as e:
            logger.debug(f"Brief learning section failed: {e}")

        # --- Suggested actions based on time of day ---
        if time_period == "morning":
            result["suggested_actions"] = [
                {"label": "Morning brief", "message": "Give me my morning brief", "icon": "clipboard"},
                {"label": "Log breakfast", "message": "Log my breakfast", "icon": "utensils"},
                {"label": "Today's schedule", "message": "What's on my schedule today?", "icon": "calendar"},
            ]
        elif time_period == "afternoon":
            result["suggested_actions"] = [
                {"label": "Log lunch", "message": "Log my lunch", "icon": "utensils"},
                {"label": "Remaining tasks", "message": "What else is on my calendar today?", "icon": "calendar"},
                {"label": "Check inbox", "message": "What's in my inbox?", "icon": "inbox"},
            ]
        elif time_period == "evening":
            result["suggested_actions"] = [
                {"label": "Log dinner", "message": "Log my dinner", "icon": "utensils"},
                {"label": "Day summary", "message": "How was my day?", "icon": "chart"},
                {"label": "Tomorrow", "message": "What's on tomorrow?", "icon": "calendar"},
            ]
        else:
            result["suggested_actions"] = [
                {"label": "Tomorrow's plan", "message": "What's tomorrow looking like?", "icon": "calendar"},
            ]

    except Exception as e:
        logger.error(f"Sara brief endpoint error: {e}")

    return result
