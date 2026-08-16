"""
Sara Status & Brief Endpoints

Exposes Sara's current internal state: emotional state, recent thoughts,
pending observations, David's energy level, and PKG stats.

Also provides the /api/sara/brief endpoint for the unified Sara screen
with time-adaptive contextual data.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from app.core.timezone import now as local_now, to_local

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.services.phase_resolution import get_effective_phase
from app.services.training_day import is_training_day
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


def _hours_since_naive_local(timestamp: datetime, now_utc: datetime) -> float:
    """Calculate age for timestamps stored as timezone-naive local wall time."""
    local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=local_tz)
    timestamp_utc = timestamp.astimezone(timezone.utc)
    elapsed_hours = (now_utc.astimezone(timezone.utc) - timestamp_utc).total_seconds() / 3600
    return round(max(0.0, elapsed_hours), 1)


def _resolve_daily_calorie_goal(db: Session, user_id: str, on_date) -> int:
    """Resolve the calorie target shown by the dashboard for a local date.

    Keep the brief aligned with the Fitness screen: an effective program phase
    wins, including its training/rest-day cycling, then the user's manually set
    nutrition goal, then the same 2,000 kcal default used by /fitness/goals.
    """
    goals_row = db.execute(text("""
        SELECT calories
        FROM fitness_goals
        WHERE user_id = :uid
        ORDER BY updated_at DESC
        LIMIT 1
    """), {"uid": user_id}).fetchone()
    fallback = goals_row.calories if goals_row and goals_row.calories is not None else 2000

    phase = get_effective_phase(db, user_id, on_date)
    if not phase:
        return int(fallback)

    training = is_training_day(db, user_id, on_date)["is_training_day"]
    cycled = phase.get("calories_training_day") if training else phase.get("calories_rest_day")
    target = cycled if cycled is not None else phase.get("calories_target")
    return int(target if target is not None else fallback)


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

        # Get pending observations from Redis (matching what debug_notifications uses)
        try:
            from app.core.redis import get_redis_sync
            r = get_redis_sync()
            obs_key = f"sara:observations:{user_id}"
            result["pending_observations"] = r.zcard(obs_key) or 0
        except Exception:
            # Fall back to journal count if Redis unavailable
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

        # Get hours since last chat from episode table (actual chat messages)
        last_chat = db.execute(text("""
            SELECT MAX(created_at) as last_at
            FROM episode
            WHERE user_id = :uid AND role = 'user'
        """), {"uid": user_id}).fetchone()

        if last_chat and last_chat.last_at:
            last_at = last_chat.last_at
            if last_at.tzinfo is None:
                from datetime import timezone as tz
                last_at = last_at.replace(tzinfo=tz.utc)
            delta_hours = (now - last_at).total_seconds() / 3600
            result["hours_since_last_chat"] = round(delta_hours, 1)

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
    hour = local_now().hour
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
            "kernel_state": "ambient",
        },
        "self_status": {"healthy": True, "degraded": []},
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

        # --- Kernel state: the one mind's live state (ONE_MIND §3.3/§3.9) ---
        # Drives the honest orb — ambient/focused/dreaming reflect real cognition,
        # not a decoration.
        try:
            from app.services.kernel import get_state as kernel_get_state
            ks = await kernel_get_state(user_id)
            result["sara_status"]["kernel_state"] = ks.get("state") or "ambient"
        except Exception as e:
            logger.debug(f"Brief kernel_state failed: {e}")

        # --- Interoception: her own body (ONE_MIND §3.1 / SINGULAR_SARA §4.2) ---
        # The greeting references her real self-state — if a body/vital is
        # down, she says so at the top of the brief instead of pretending
        # she's whole. Only surfaced when actually degraded.
        #
        # Sourced from the canonical body-state projection so this can never
        # disagree with /api/metrics or /analytics/dashboard about the same
        # component (SINGULAR_SARA_MASTER_PLAN §13 item 3) — `self_status`
        # keeps its old {healthy, degraded} shape for existing callers;
        # `body_state` carries the full versioned projection for new ones.
        try:
            from app.services.body_state_projection import get_body_state_projection
            projection = await get_body_state_projection(user_id)
            degraded_components = [c for c in projection.components if c.status.value == "degraded"]
            self_status = {
                "healthy": projection.healthy,
                "degraded": [
                    {"subsystem": c.name, "name": c.label or c.name, "impact": c.impact, "severity": c.severity}
                    for c in degraded_components
                ],
            }
            result["self_status"] = self_status
            result["body_state"] = projection.model_dump(mode="json")
            if not self_status["healthy"] and self_status["degraded"]:
                degraded = self_status["degraded"]
                names = ", ".join(d["name"] for d in degraded)
                result["brief_sections"].insert(0, {
                    "type": "self_status",
                    "title": "I'm running degraded",
                    "priority": "high",
                    "content": f"{names} — {degraded[0]['impact']}.",
                    "data": {"degraded": degraded},
                })
        except Exception as e:
            db.rollback()
            logger.debug(f"Brief self_status section failed: {e}")

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
            db.rollback()
            logger.debug(f"Brief calendar section failed: {e}")

        # --- Fitness/nutrition section ---
        try:
            today_start_local, today_end_local = _local_day_bounds_naive(now)
            calorie_goal = _resolve_daily_calorie_goal(
                db, user_id, today_start_local.date()
            )
            food_stats = db.execute(text("""
                SELECT COALESCE(SUM(calories), 0) as cal,
                       COALESCE(SUM(protein), 0) as pro,
                       MAX(logged_at) as last_meal
                FROM food_log
                WHERE user_id = :uid
                  AND logged_at >= :start
                  AND logged_at < :end
            """), {
                "uid": user_id,
                "start": today_start_local,
                "end": today_end_local,
            }).fetchone()

            if food_stats:
                last_meal_ago = None
                if food_stats.last_meal:
                    try:
                        last_meal_ago = _hours_since_naive_local(food_stats.last_meal, now)
                    except Exception:
                        pass

                result["brief_sections"].append({
                    "type": "fitness",
                    "data": {
                        "calories_today": int(food_stats.cal or 0),
                        "protein_today": int(food_stats.pro or 0),
                        "goal": calorie_goal,
                        "last_meal_ago_hours": last_meal_ago,
                    },
                })
        except Exception as e:
            db.rollback()
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
            db.rollback()
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
            db.rollback()
            logger.debug(f"Brief learning section failed: {e}")

        # --- Fact verification (ONE_MIND §3.4): one gentle memory-check in the
        # evening recap. Displayed (mark_asked=False) so it persists until David
        # answers; answering hits /api/memory/verification-answer to graduate or
        # retire the fact. ---
        if time_period in ("evening", "night"):
            try:
                from app.services.fact_verification import pick_question
                vq = await pick_question(user_id=user_id, mark_asked=False)
                if vq:
                    result["brief_sections"].append({
                        "type": "verification",
                        "title": "Quick memory check",
                        "priority": "low",
                        "content": vq["question"],
                        "data": {"pkg_id": vq["pkg_id"], "fact": vq["fact"]},
                    })
            except Exception as e:
                db.rollback()
                logger.debug(f"Brief verification section failed: {e}")

        # --- needs_you: reuse the unified inbox formula (single source of
        # truth, do not reimplement), minus Sara's own self-maintenance
        # categories — those stay reachable in the inbox at FYI tier but
        # don't occupy the dashboard's amber "needs you" slot. ---
        try:
            from app.routes.assistant_inbox import build_unified_inbox, compute_badge
            from app.services.autonomy.attention_queue import SELF_MAINTENANCE_CATEGORIES

            inbox = build_unified_inbox(db, user_id)
            filtered_needs_you = [
                item for item in (inbox.get("needs_you") or [])
                if (item.get("category") or "") not in SELF_MAINTENANCE_CATEGORIES
            ]
            result["needs_you"] = {
                "items": filtered_needs_you[:3],
                "total": len(filtered_needs_you),
                "badge": compute_badge(db, user_id),
            }
        except Exception as e:
            db.rollback()
            logger.debug(f"Brief needs_you section failed: {e}")

        # --- ongoing: active timers + standing orders firing in the next
        # 12h (ET). Shares compute_order_fires_at with /api/standing-orders
        # so the two surfaces never disagree about when something fires. ---
        try:
            from app.routes.standing_orders import compute_order_fires_at

            now_et = local_now()
            horizon = now_et + timedelta(hours=12)
            ongoing_items: List[Dict[str, Any]] = []

            timer_rows = db.execute(text("""
                SELECT id, title, end_time FROM timer
                WHERE user_id = :uid AND is_active = true AND is_completed = false
                ORDER BY end_time
            """), {"uid": user_id}).fetchall()
            for t in timer_rows:
                fires_at = to_local(t.end_time) if t.end_time else None
                ongoing_items.append({
                    "kind": "timer",
                    "id": str(t.id),
                    "title": t.title,
                    "fires_at": fires_at.isoformat() if fires_at else None,
                })

            order_rows = db.execute(text("""
                SELECT id, description, trigger_type, trigger_config
                FROM standing_order
                WHERE user_id = :uid AND status = 'active'
            """), {"uid": user_id}).fetchall()
            for r in order_rows:
                tc = r.trigger_config if isinstance(r.trigger_config, dict) else json.loads(r.trigger_config or "{}")
                fires_at = compute_order_fires_at(db, user_id, r.trigger_type, tc)
                if fires_at and now_et <= fires_at <= horizon:
                    ongoing_items.append({
                        "kind": "standing_order",
                        "id": str(r.id),
                        "title": r.description,
                        "fires_at": fires_at.isoformat(),
                    })

            ongoing_items.sort(key=lambda x: x["fires_at"] or "9999")
            result["ongoing"] = ongoing_items
        except Exception as e:
            db.rollback()
            logger.debug(f"Brief ongoing section failed: {e}")

        # --- journal: up to 3 deduped first-person entries, same rule as
        # /api/sara/activity's journal branch (0D). ---
        try:
            from app.routes.sara_activity import get_deduped_journal_entries

            entries = get_deduped_journal_entries(db, user_id, hours=24, raw_limit=20, max_results=3)
            result["journal"] = [
                {
                    "id": e["id"],
                    "content": e["content"],
                    "timestamp": e["timestamp"],
                    "emotional_state": e["emotional_state"],
                }
                for e in entries
            ]
        except Exception as e:
            db.rollback()
            logger.debug(f"Brief journal section failed: {e}")

        # --- digest ("while you were away"): Mind V2's judge->compose->review
        # pipeline (composed_utterance) is the primary source — David's shadow
        # -week reading surface for what Sara would have said. Falls back to
        # the raw sara_activity_log audience=user_facing rule (0A/Phase 1) on
        # cold days with no composed rows in the window. Payload shape is
        # unchanged either way: {items: [{text, at, delivered}], machinery}. ---
        try:
            digest_since = now - timedelta(hours=24)

            composed_rows = db.execute(text("""
                SELECT text, final_text, slot, created_at, delivered_at
                FROM composed_utterance
                WHERE user_id = :uid AND created_at >= :since
                  AND review_verdict IN ('approve', 'edit')
                ORDER BY (slot IS NOT NULL) DESC, created_at DESC
                LIMIT 6
            """), {"uid": user_id, "since": digest_since}).fetchall()

            if composed_rows:
                digest_items = [
                    {
                        "text": row.final_text or row.text,
                        "at": row.created_at.isoformat() if row.created_at else None,
                        "delivered": row.delivered_at is not None,
                    }
                    for row in composed_rows
                ]
            else:
                HUMAN_KINDS = {"thought", "reflection", "focus_set", "notify_david", "inbox_pickup", "inbox_complete"}
                human_rows = db.execute(text("""
                    SELECT kind, summary, created_at FROM sara_activity_log
                    WHERE audience = 'user_facing' AND created_at >= :since
                    ORDER BY created_at DESC LIMIT 60
                """), {"since": digest_since}).fetchall()

                digest_items = []
                last_summary = None
                for row in human_rows:
                    if row.kind not in HUMAN_KINDS or row.summary == last_summary:
                        continue
                    digest_items.append({
                        "text": row.summary,
                        "at": row.created_at.isoformat() if row.created_at else None,
                        "delivered": True,
                    })
                    last_summary = row.summary
                    if len(digest_items) >= 6:
                        break

            MACHINE_KINDS = {"tool_call", "tool_result", "error"}
            machine_rows = db.execute(text("""
                SELECT kind FROM sara_activity_log
                WHERE (audience = 'internal' OR audience IS NULL) AND created_at >= :since
                ORDER BY created_at DESC LIMIT 30
            """), {"since": digest_since}).fetchall()
            machine_kinds_seen = [r.kind for r in machine_rows if r.kind in MACHINE_KINDS]

            result["digest"] = {
                "items": digest_items,
                "machinery": {
                    "tool_calls": sum(1 for k in machine_kinds_seen if k in ("tool_call", "tool_result")),
                    "errors": sum(1 for k in machine_kinds_seen if k == "error"),
                },
            }
        except Exception as e:
            db.rollback()
            logger.debug(f"Brief digest section failed: {e}")

        # --- weather: server-side so iOS gets it too (web currently fetches
        # it separately via /api/morning-brief/weather). ---
        try:
            from app.services.weather_service import weather_service

            weather = await weather_service.get_weather()
            if weather:
                result["weather"] = weather.to_dict()
        except Exception as e:
            logger.debug(f"Brief weather section failed: {e}")

        # --- quiet_line: on an empty day (no calendar events, no digest
        # items) the renderer collapses to one line instead of stacking five
        # "No X today" placeholders — the most recent journal entry's first
        # sentence, since that's already Sara's own read on the day. ---
        try:
            calendar_empty = not any(s.get("type") == "calendar" for s in result["brief_sections"])
            digest_empty = not (result.get("digest") or {}).get("items")
            if calendar_empty and digest_empty and result.get("journal"):
                first_content = result["journal"][0]["content"] or ""
                sentence_end = re.search(r"[.!?](\s|$)", first_content)
                result["quiet_line"] = first_content[:sentence_end.end()].strip() if sentence_end else first_content.strip()
        except Exception as e:
            logger.debug(f"Brief quiet_line failed: {e}")

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
        db.rollback()
        logger.error(f"Sara brief endpoint error: {e}")

    return result
