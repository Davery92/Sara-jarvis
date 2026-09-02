"""
Daily Log / Diary — one prose entry per day, written in Sara's voice.

DAILY_LOG_DIARY_PLAN_2026_08_25. The shape of this service is deliberate:

* **No agent loop, no tool calls.** Everything the model sees is pulled
  deterministically by SQL (``day_replay_builder`` plus the supplemental
  collectors below), formatted into a plain-text fact sheet by
  ``render_facts()``, and handed over in ONE bounded prompt. The model's only
  job is prose — every number in the entry was computed in Python.
* **The structured facts are kept.** ``generate()`` writes the prose into the
  long-unused ``day_replay_cache.summary`` column *alongside* the replay JSON,
  so the UI can show receipts under the diary text.
* **Failure-isolated.** If the LLM call fails the structured replay is still
  cached and ``summary`` stays NULL; the regenerate endpoint is the retry.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.llm import get_background_llm_client
from app.core.timezone import USER_TIMEZONE
from app.services.context_budget import CHARS_PER_TOKEN, estimate_tokens
from app.services.day_replay_builder import (
    DayBounds,
    DayReplay,
    day_bounds,
    day_replay_builder,
    utc_naive_to_et_naive,
)

logger = logging.getLogger(__name__)

# Fact-sheet budget. ~6k tokens of facts leaves plenty of headroom on the
# background lane while still fitting a busy day comfortably.
MAX_FACT_TOKENS = 6000

# Bounded output. Non-negotiable per the 2026-08-19 llama-server runaway
# incident: a background call with no cap generated for ~25 minutes.
DIARY_MAX_TOKENS = 700
DIARY_TIMEOUT_SECONDS = 120.0

# Cumulative-snapshot metrics: Apple Health reports a running daily total, so
# the day's value is MAX(), never SUM(). (gotcha_steps_cumulative)
CUMULATIVE_METRICS = {"steps", "flights_climbed", "active_energy", "exercise_minutes", "stand_minutes"}

# sara_journal entry types kept out of the fact sheet, because they are Sara
# reasoning rather than Sara observing: `self_story` is her own inner arc, and
# `theory_of_david` / `consolidation` are her running guesses about his state.
# Found 2026-08-25 that a quiet Wednesday's entry got written almost entirely
# out of `consolidation` notes, laundering "focused, solitary productivity"
# into the record as though it had been observed. What survives are the entries
# that record something she actually did or said (deliberation, reviews, etc.),
# and the prompt still labels those as her read at the time.
EXCLUDED_JOURNAL_TYPES = {"self_story", "theory_of_david", "consolidation"}


DIARY_SYSTEM_PROMPT = """You are Sara, David's personal AI assistant, writing \
the private diary entry for his day. You write it at night, after he's gone to \
bed, the way a sharp friend would jot down what the day actually was."""


DIARY_PROMPT = """Write the diary entry for {weekday}, {date_long} using ONLY the facts below.

How to write it:
- First person for you — always "I", never "Sara". Third person for him — \
"David", "he". Past tense. This is your record of his day, not a letter \
written to him, so never address him as "you".
- Any number you use must be copied exactly from the facts. If you can't \
copy it exactly, leave it out.
- 150-300 words, flowing prose. No headings, no bullet lists, no markdown.
- Tell the shape of the day: what he did, what it added up to, what stood out.
- The dry numbers live in the receipts below the entry, not in the prose. Use \
a number only when it carries the point (a PR, an unusually short night, a \
day he clearly under-ate).
- Warm and observant, not a status report. No "Summary:", no sign-off, no \
questions, no offers of help, no advice for tomorrow.
- If a section is missing below, do not mention that part of his life at all.
- Do NOT invent events, numbers, people, or feelings about anything not listed. \
If the facts are thin, write a short entry — a thin day is a real thing to note.
- Calendar entries marked as someone else's are NOT things David did.
- The "My own notes and messages" section is what YOU thought and said that \
day. Your notes there are guesses you made at the time, not observations — \
never restate one as something that happened. The entry is about HIS day, not \
yours: never narrate your own machinery, checks, sweeps, or feelings about \
being an assistant.
- Do not describe his mood, focus, energy, or what he was thinking unless a \
fact below actually records it.
- Two or three paragraphs, and stop. Do not stretch a quiet day into a long one.{thin_note}

FACTS FOR {date_iso}
{facts}
"""


@dataclass
class DailyLogResult:
    """Outcome of one generate() run."""
    log_date: date
    diary: Optional[str]
    payload: Dict[str, Any]
    facts: str
    total_events: int
    cached: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.log_date.isoformat(),
            "diary": self.diary,
            "sections": sorted(k for k, v in self.payload.items() if _has_content(v)),
            "total_events": self.total_events,
            "cached": self.cached,
            "error": self.error,
        }


def _has_content(value: Any) -> bool:
    """True if there is anything real in here.

    Recurses into dicts: the section builders return fixed-shape dicts
    (``{"summaries": None, "sessions": []}``), so a plain truthiness test
    would call every section non-empty on every day.
    """
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_has_content(v) for v in value.values())
    if isinstance(value, (list, tuple, str)):
        return len(value) > 0
    return True


def _fmt_time(dt: Optional[datetime]) -> str:
    """Render a timestamp as ET wall-clock.

    Replay event timestamps are already naive ET; rows read straight from
    timestamptz columns arrive aware and are converted here.
    """
    if dt is None:
        return "??:??"
    if dt.tzinfo is not None:
        dt = dt.astimezone(USER_TIMEZONE)
    return dt.strftime("%-I:%M %p")


def _round(value: Any, digits: int = 0) -> Any:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return int(round(num)) if digits == 0 else round(num, digits)


class DailyLogService:
    """Builds and stores the per-day diary entry."""

    # ------------------------------------------------------------------
    # 2a. Payload
    # ------------------------------------------------------------------

    async def build_payload(
        self,
        db: Session,
        user_id: str,
        log_date: date,
        replay: Optional[DayReplay] = None,
    ) -> Dict[str, Any]:
        """Collect everything that happened on ``log_date`` (an ET calendar day).

        ``replay`` may be passed in by a caller that already built one (the
        dream cycle does) to avoid running the twelve collectors twice.
        """
        if replay is None:
            replay = await day_replay_builder.build_replay(db, user_id, log_date)

        bounds = day_bounds(log_date)
        by_type: Dict[str, List[Any]] = {}
        for event in replay.events:
            by_type.setdefault(event.event_type, []).append(event)

        payload: Dict[str, Any] = {
            "date": log_date.isoformat(),
            "weekday": log_date.strftime("%A"),
            "chat": self._section_chat(user_id, log_date, by_type),
            "fitness": self._section_fitness(db, user_id, bounds, by_type),
            "nutrition": self._section_nutrition(by_type),
            "recovery": self._section_recovery(by_type),
            "calendar": self._section_calendar(by_type),
            "tasks": self._section_tasks(by_type),
            "learning": self._section_learning(by_type),
            "notes": self._collect_notes(db, user_id, bounds),
            "sara": self._section_sara(db, user_id, bounds),
            "misc": self._section_misc(by_type),
        }
        payload["counts"] = {
            "total_events": replay.total_events,
            "sources": replay.data_sources_included,
        }
        return payload

    # -- chat ----------------------------------------------------------

    def _section_chat(
        self, user_id: str, log_date: date, by_type: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """Prose summaries of the day's conversations.

        The live day layer is archived and cleared at midnight ET, so by the
        time the 2 AM dream cycle runs ``day_layer.read()`` holds the *new*
        day. Read the archive for this specific date instead. If the archive
        is empty but episodes exist, fall back to the conversations themselves.
        """
        sessions = []
        for event in by_type.get("conversation", []):
            details = event.details or {}
            sessions.append({
                "time": _fmt_time(event.timestamp),
                "messages": details.get("message_count"),
                "user_messages": details.get("user_message_count"),
                "duration_minutes": details.get("duration_minutes"),
                "topics": [t for t in (details.get("sample_topics") or []) if t],
                "importance": event.importance,
            })

        summary_text = None
        try:
            from app.services.daily_brief.archiver import archiver
            summary_text = archiver.get_archived_day_layer(user_id, log_date)
        except Exception as e:
            logger.warning(f"Daily log: archived day layer unavailable: {e}")

        if summary_text:
            # The archived layer carries its own "## Today (Monday, August 24)"
            # header; the fact sheet supplies section headings itself.
            summary_text = re.sub(r"^##\s*Today\s*\([^)]*\)\s*", "", summary_text.strip())
            summary_text = summary_text.strip() or None

        return {"summaries": summary_text, "sessions": sessions}

    # -- fitness -------------------------------------------------------

    def _section_fitness(
        self, db: Session, user_id: str, bounds: DayBounds, by_type: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        workouts = []
        for event in by_type.get("workout_completed", []):
            details = event.details or {}
            workouts.append({
                "time": _fmt_time(event.timestamp),
                "type": details.get("workout_type"),
                "duration_minutes": details.get("duration_minutes"),
            })

        return {
            "workouts": workouts,
            "lifting": self._collect_lifting(db, user_id, bounds),
            "cardio": self._collect_cardio(db, user_id, bounds),
            "activity": self._collect_activity_metrics(db, user_id, bounds),
        }

    def _collect_lifting(self, db: Session, user_id: str, bounds: DayBounds) -> Dict[str, Any]:
        """Working-set totals and PRs from workout_log (keyed on session_date, a DATE)."""
        try:
            rows = db.execute(
                text("""
                    SELECT exercise_id, COUNT(*) AS sets,
                           SUM(COALESCE(weight, 0) * COALESCE(reps, 0)) AS volume,
                           MAX(COALESCE(weight, 0)) AS top_weight,
                           BOOL_OR(COALESCE(is_pr, false)) AS had_pr
                    FROM workout_log
                    WHERE user_id = :user_id
                      AND session_date = :session_date
                      AND COALESCE(skipped, false) = false
                      AND voided_at IS NULL
                      AND COALESCE(set_kind, 'working') = 'working'
                    GROUP BY exercise_id
                    ORDER BY volume DESC NULLS LAST
                """),
                {"user_id": user_id, "session_date": bounds.replay_date},
            ).fetchall()
        except Exception as e:
            logger.warning(f"Daily log: lifting collector failed: {e}")
            db.rollback()
            return {}

        if not rows:
            return {}

        exercises = [{
            "name": r.exercise_id,
            "sets": int(r.sets or 0),
            "volume": _round(r.volume),
            "top_weight": _round(r.top_weight),
            "pr": bool(r.had_pr),
        } for r in rows]

        return {
            "exercises": exercises,
            "total_sets": sum(e["sets"] for e in exercises),
            "total_volume": sum(e["volume"] or 0 for e in exercises),
            "prs": [e["name"] for e in exercises if e["pr"]],
        }

    def _collect_cardio(self, db: Session, user_id: str, bounds: DayBounds) -> List[Dict[str, Any]]:
        """cardio_log — the cardio/Tabata tracker, which postdates day_replay_builder."""
        try:
            rows = db.execute(
                text("""
                    SELECT activity_type, title, duration_minutes, distance_miles,
                           avg_hr, max_hr, zone, calories_burned, rpe, notes, logged_at
                    FROM cardio_log
                    WHERE user_id = :user_id
                      AND session_date = :session_date
                    ORDER BY logged_at
                """),
                {"user_id": user_id, "session_date": bounds.replay_date},
            ).fetchall()
        except Exception as e:
            logger.warning(f"Daily log: cardio collector failed: {e}")
            db.rollback()
            return []

        return [{
            "activity": r.activity_type,
            "title": r.title,
            "duration_minutes": _round(r.duration_minutes),
            "distance_miles": _round(r.distance_miles, 2),
            "avg_hr": r.avg_hr,
            "max_hr": r.max_hr,
            "zone": r.zone,
            "calories": _round(r.calories_burned),
            "rpe": r.rpe,
            "notes": (r.notes or "")[:200] or None,
        } for r in rows]

    def _collect_activity_metrics(
        self, db: Session, user_id: str, bounds: DayBounds
    ) -> Dict[str, Any]:
        """Apple Health day totals.

        steps/flights/active-energy are *cumulative daily snapshots* — the last
        reading of the day IS the day's total, so aggregate with MAX, never SUM
        (gotcha_steps_cumulative). The day being rendered is always a completed
        day, so there is no partial-day case to exclude.
        """
        try:
            rows = db.execute(
                text("""
                    SELECT metric_type, MAX(value) AS max_value, AVG(value) AS avg_value
                    FROM health_metric
                    WHERE user_id = :user_id
                      AND recorded_at BETWEEN :day_start AND :day_end
                    GROUP BY metric_type
                """),
                {"user_id": user_id,
                 "day_start": bounds.aware_start, "day_end": bounds.aware_end},
            ).fetchall()
        except Exception as e:
            logger.warning(f"Daily log: activity metrics collector failed: {e}")
            db.rollback()
            return {}

        metrics: Dict[str, Any] = {}
        for r in rows:
            if r.metric_type in CUMULATIVE_METRICS:
                metrics[r.metric_type] = _round(r.max_value)
            else:
                metrics[r.metric_type] = _round(r.avg_value, 1)
        return metrics

    # -- nutrition -----------------------------------------------------

    def _section_nutrition(self, by_type: Dict[str, List[Any]]) -> Dict[str, Any]:
        meals = []
        totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
        for event in by_type.get("meal_logged", []):
            details = event.details or {}
            meals.append({
                "time": _fmt_time(event.timestamp),
                "meal": details.get("meal_type"),
                "description": (details.get("description") or "")[:120],
                "calories": _round(details.get("calories")),
                "protein": _round(details.get("protein")),
            })
            for key, field in (("calories", "calories"), ("protein", "protein"),
                               ("carbs", "carbs"), ("fat", "fat")):
                value = _round(details.get(field))
                if value:
                    totals[key] += value

        if not meals:
            return {}
        return {"meals": meals, "totals": totals}

    # -- recovery ------------------------------------------------------

    def _section_recovery(self, by_type: Dict[str, List[Any]]) -> Dict[str, Any]:
        events = by_type.get("recovery_metrics", [])
        if not events:
            return {}
        details = events[0].details or {}
        return {
            "sleep_hours": _round(details.get("sleep_hours"), 1),
            "hrv": _round(details.get("hrv"), 1),
            "resting_hr": _round(details.get("resting_hr")),
            "soreness": details.get("soreness_level"),
            "body_weight": _round(details.get("body_weight"), 1),
        }

    # -- calendar ------------------------------------------------------

    def _section_calendar(self, by_type: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        entries = []
        for event in by_type.get("calendar_event", []):
            details = event.details or {}
            entries.append({
                "time": _fmt_time(event.timestamp),
                "title": details.get("title"),
                "location": details.get("location"),
                "duration_minutes": details.get("duration_minutes"),
                # Ownership matters: someone else's appointment is not
                # something David did, and the prompt says so explicitly.
                "owner": details.get("owner") or "self",
                "is_davids": bool(details.get("is_davids")),
            })
        return entries

    # -- tasks ---------------------------------------------------------

    def _section_tasks(self, by_type: Dict[str, List[Any]]) -> Dict[str, Any]:
        agent_tasks = []
        for event in by_type.get("research_task", []):
            details = event.details or {}
            agent_tasks.append({
                "time": _fmt_time(event.timestamp),
                "type": details.get("task_type"),
                "description": (details.get("description") or "")[:160],
                "status": details.get("status"),
            })

        reminders = {}
        for event in by_type.get("reminders_summary", []):
            details = event.details or {}
            reminders = {
                "total": details.get("total"),
                "completed": details.get("completed"),
                "items": [
                    {"title": r.get("title"), "completed": r.get("completed")}
                    for r in (details.get("reminders") or [])
                ],
            }

        timers = {}
        for event in by_type.get("timers_summary", []):
            details = event.details or {}
            timers = {
                "count": details.get("timer_count"),
                "items": [t.get("title") for t in (details.get("timers") or [])],
            }

        section: Dict[str, Any] = {}
        if agent_tasks:
            section["agent_tasks"] = agent_tasks
        if reminders:
            section["reminders"] = reminders
        if timers:
            section["timers"] = timers
        return section

    # -- learning ------------------------------------------------------

    def _section_learning(self, by_type: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        sessions = []
        for event in by_type.get("learning_session", []):
            details = event.details or {}
            sessions.append({
                "time": _fmt_time(event.timestamp),
                "topic": details.get("topic"),
                "type": details.get("session_type"),
                "duration_minutes": details.get("duration_minutes"),
            })
        return sessions

    # -- notes ---------------------------------------------------------

    def _collect_notes(self, db: Session, user_id: str, bounds: DayBounds) -> List[Dict[str, Any]]:
        """Notes touched that day. Title + folder only — the bodies would swamp
        the fact sheet and the diary is about the day, not the content.

        note.created_at/updated_at are naive UTC (PG NOW() on a UTC session).
        """
        try:
            rows = db.execute(
                text("""
                    SELECT n.title, f.name AS folder, n.created_at, n.updated_at
                    FROM note n
                    LEFT JOIN folder f ON f.id = n.folder_id
                    WHERE n.user_id = :user_id
                      AND (n.created_at BETWEEN :day_start AND :day_end
                           OR n.updated_at BETWEEN :day_start AND :day_end)
                    ORDER BY COALESCE(n.updated_at, n.created_at)
                    LIMIT 40
                """),
                {"user_id": user_id,
                 "day_start": bounds.utc_naive_start, "day_end": bounds.utc_naive_end},
            ).fetchall()
        except Exception as e:
            logger.warning(f"Daily log: notes collector failed: {e}")
            db.rollback()
            return []

        notes = []
        for r in rows:
            created = utc_naive_to_et_naive(r.created_at)
            is_new = created is not None and created.date() == bounds.replay_date
            notes.append({
                "title": r.title,
                "folder": r.folder,
                "action": "created" if is_new else "edited",
                "time": _fmt_time(utc_naive_to_et_naive(r.updated_at) or created),
            })
        return notes

    # -- Sara's own day ------------------------------------------------

    def _section_sara(self, db: Session, user_id: str, bounds: DayBounds) -> Dict[str, Any]:
        section: Dict[str, Any] = {}

        try:
            rows = db.execute(
                text("""
                    SELECT entry_type, content, emotional_state, created_at
                    FROM sara_journal
                    WHERE user_id = :user_id
                      AND created_at BETWEEN :day_start AND :day_end
                      AND COALESCE(entry_type, '') <> ALL(:excluded)
                    ORDER BY created_at
                    LIMIT 30
                """),
                {"user_id": user_id,
                 "day_start": bounds.aware_start, "day_end": bounds.aware_end,
                 "excluded": sorted(EXCLUDED_JOURNAL_TYPES)},
            ).fetchall()
            entries = self._dedupe_journal([{
                "time": _fmt_time(r.created_at),
                "type": r.entry_type,
                "mood": r.emotional_state,
                "content": (r.content or "")[:300],
            } for r in rows])
            if entries:
                section["journal"] = entries
        except Exception as e:
            logger.warning(f"Daily log: sara_journal collector failed: {e}")
            db.rollback()

        try:
            rows = db.execute(
                text("""
                    SELECT category, title, message, priority, sent_at, engaged
                    FROM notification_log
                    WHERE user_id = :user_id
                      AND sent_at BETWEEN :day_start AND :day_end
                      AND COALESCE(sent, false) = true
                    ORDER BY sent_at
                    LIMIT 40
                """),
                {"user_id": user_id,
                 "day_start": bounds.aware_start, "day_end": bounds.aware_end},
            ).fetchall()
            delivered = [{
                "time": _fmt_time(r.sent_at),
                "category": r.category,
                "title": r.title,
                "message": (r.message or "")[:200],
                "engaged": bool(r.engaged),
            } for r in rows]
            if delivered:
                section["notifications"] = delivered
        except Exception as e:
            logger.warning(f"Daily log: notification_log collector failed: {e}")
            db.rollback()

        return section

    @staticmethod
    def _dedupe_journal(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse Sara's night-watch repetition.

        The deliberation loop writes a near-identical "the house is quiet, locks
        checked" entry every few minutes. Six copies of it in the fact sheet
        would dominate the day and pull the diary toward Sara's own machinery
        instead of David's day.
        """
        seen = set()
        deliberations = 0
        kept: List[Dict[str, Any]] = []
        for entry in entries:
            fingerprint = (entry.get("content") or "")[:60].lower()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            if entry.get("type") == "deliberation":
                deliberations += 1
                if deliberations > 2:
                    continue
            kept.append(entry)
        return kept

    # -- misc ----------------------------------------------------------

    def _section_misc(self, by_type: Dict[str, List[Any]]) -> Dict[str, Any]:
        section: Dict[str, Any] = {}

        for event in by_type.get("email_summary", []):
            details = event.details or {}
            section["email"] = {
                "received": details.get("total_received"),
                "high_priority": details.get("high_priority"),
                "read": details.get("read_count"),
            }

        automations = []
        for event in by_type.get("automation_pattern", []):
            details = event.details or {}
            automations.append({
                "name": details.get("automation_name"),
                "runs": details.get("run_count"),
                "successful": details.get("successful_runs"),
            })
        if automations:
            section["automations"] = automations

        # Home activity is per-entity transition noise — useful for pattern
        # detection, useless as diary prose. Keep only the headline count so
        # the model can say "the house did its usual thing" and nothing more.
        home_events = by_type.get("home_entity_activity", [])
        if home_events:
            section["home"] = {
                "entities": len({(e.details or {}).get("entity_id") for e in home_events}),
                "transitions": sum(int((e.details or {}).get("change_count") or 0) for e in home_events),
            }

        return section

    # ------------------------------------------------------------------
    # 2b. Fact sheet
    # ------------------------------------------------------------------

    def render_facts(self, payload: Dict[str, Any]) -> str:
        """Deterministic plain-text fact sheet. Every number here was computed
        in Python; the model never does arithmetic.

        Empty sections are omitted entirely so the model isn't tempted to pad.
        """
        blocks: List[str] = []

        def block(title: str, lines: List[str]) -> None:
            lines = [ln for ln in lines if ln]
            if lines:
                blocks.append(f"## {title}\n" + "\n".join(lines))

        # -- conversations
        chat = payload.get("chat") or {}
        chat_lines: List[str] = []
        if chat.get("summaries"):
            chat_lines.append(chat["summaries"].strip())
        sessions = chat.get("sessions") or []
        if sessions:
            chat_lines.append(f"({len(sessions)} conversation session"
                              f"{'s' if len(sessions) != 1 else ''} total)")
            if not chat.get("summaries"):
                # No archived prose summary — fall back to the conversations
                # themselves, highest-importance first, bounded.
                ranked = sorted(sessions, key=lambda s: -(s.get("importance") or 0))
                for session in ranked[:8]:
                    topics = "; ".join(t.strip() for t in session.get("topics") or [])
                    chat_lines.append(
                        f"- {session['time']} — {session.get('messages') or 0} messages"
                        + (f": {topics}" if topics else "")
                    )
        block("Conversations", chat_lines)

        # -- training
        fitness = payload.get("fitness") or {}
        fit_lines: List[str] = []
        for workout in fitness.get("workouts") or []:
            duration = workout.get("duration_minutes")
            fit_lines.append(
                f"- {workout['time']} — completed {workout.get('type') or 'workout'}"
                + (f" ({duration} min)" if duration else "")
            )
        lifting = fitness.get("lifting") or {}
        if lifting:
            fit_lines.append(
                f"- Lifting: {lifting['total_sets']} working sets, "
                f"{lifting['total_volume']:,} lb total volume"
            )
            for exercise in (lifting.get("exercises") or [])[:8]:
                fit_lines.append(
                    f"    - {exercise['name']}: {exercise['sets']} sets, "
                    f"top {exercise['top_weight']} lb"
                    + (" (PR)" if exercise["pr"] else "")
                )
            extra = len(lifting.get("exercises") or []) - 8
            if extra > 0:
                fit_lines.append(f"    - …and {extra} more exercises")
            if lifting.get("prs"):
                fit_lines.append(f"- PRs today: {', '.join(lifting['prs'])}")
        for cardio in fitness.get("cardio") or []:
            parts = [f"{cardio['duration_minutes']} min"] if cardio.get("duration_minutes") else []
            if cardio.get("distance_miles"):
                parts.append(f"{cardio['distance_miles']} mi")
            if cardio.get("avg_hr"):
                parts.append(f"avg HR {cardio['avg_hr']}")
            if cardio.get("zone"):
                parts.append(f"zone {cardio['zone']}")
            fit_lines.append(
                f"- Cardio: {cardio.get('title') or cardio.get('activity')}"
                + (f" — {', '.join(parts)}" if parts else "")
            )
        activity = fitness.get("activity") or {}
        if activity:
            labels = {
                "steps": "steps", "flights_climbed": "flights climbed",
                "active_energy": "active kcal", "exercise_minutes": "exercise minutes",
                "stand_minutes": "stand minutes",
            }
            shown = [f"{activity[k]:,} {label}" for k, label in labels.items()
                     if activity.get(k)]
            if shown:
                fit_lines.append("- Activity: " + ", ".join(shown))
        block("Training & movement", fit_lines)

        # -- nutrition
        nutrition = payload.get("nutrition") or {}
        if nutrition:
            totals = nutrition["totals"]
            nut_lines = [
                f"- Day totals: {totals['calories']:,} kcal, {totals['protein']}g protein, "
                f"{totals['carbs']}g carbs, {totals['fat']}g fat "
                f"across {len(nutrition['meals'])} logged items"
            ]
            for meal in nutrition["meals"][:12]:
                nut_lines.append(
                    f"- {meal['time']} {meal.get('meal') or 'meal'}: "
                    f"{meal.get('description') or 'logged'}"
                    + (f" ({meal['calories']} kcal)" if meal.get("calories") else "")
                )
            extra = len(nutrition["meals"]) - 12
            if extra > 0:
                nut_lines.append(f"- …and {extra} more logged items")
            block("Nutrition", nut_lines)

        # -- recovery
        recovery = payload.get("recovery") or {}
        if recovery:
            labels = [
                ("sleep_hours", "sleep", "h"), ("hrv", "HRV", ""),
                ("resting_hr", "resting HR", " bpm"), ("soreness", "soreness", "/10"),
                ("body_weight", "weight", " lb"),
            ]
            shown = [f"{name} {recovery[key]}{unit}" for key, name, unit in labels
                     if recovery.get(key) is not None]
            block("Recovery", [f"- {', '.join(shown)}"] if shown else [])

        # -- calendar
        calendar = payload.get("calendar") or []
        cal_lines = []
        for entry in calendar[:15]:
            marker = "" if entry.get("is_davids") else \
                f" [{entry.get('owner')}'s event — NOT David's]"
            cal_lines.append(
                f"- {entry['time']} {entry.get('title')}"
                + (f" @ {entry['location']}" if entry.get("location") else "")
                + marker
            )
        if len(calendar) > 15:
            cal_lines.append(f"- …and {len(calendar) - 15} more events")
        block("Calendar", cal_lines)

        # -- work / tasks
        tasks = payload.get("tasks") or {}
        task_lines = []
        for task in (tasks.get("agent_tasks") or [])[:10]:
            task_lines.append(
                f"- {task['time']} {task.get('type') or 'task'}: "
                f"{task.get('description')} ({task.get('status')})"
            )
        extra = len(tasks.get("agent_tasks") or []) - 10
        if extra > 0:
            task_lines.append(f"- …and {extra} more agent tasks")
        reminders = tasks.get("reminders") or {}
        if reminders:
            task_lines.append(
                f"- Reminders: {reminders.get('completed')}/{reminders.get('total')} completed"
            )
            for item in (reminders.get("items") or [])[:6]:
                mark = "done" if item.get("completed") else "open"
                task_lines.append(f"    - {item.get('title')} ({mark})")
        timers = tasks.get("timers") or {}
        if timers:
            names = ", ".join(t for t in (timers.get("items") or []) if t)
            task_lines.append(f"- Timers used: {timers.get('count')}"
                              + (f" ({names})" if names else ""))
        block("Tasks & agent work", task_lines)

        # -- learning
        learn_lines = [
            f"- {s['time']} {s.get('topic') or 'topic'} — {s.get('duration_minutes')} min "
            f"({s.get('type')})"
            for s in (payload.get("learning") or [])[:10]
        ]
        block("Learning", learn_lines)

        # -- notes
        notes = payload.get("notes") or []
        note_lines = [
            f"- {n['action']} \"{n.get('title')}\""
            + (f" in {n['folder']}" if n.get("folder") else "")
            for n in notes[:12]
        ]
        if len(notes) > 12:
            note_lines.append(f"- …and {len(notes) - 12} more notes")
        block("Notes", note_lines)

        # -- Sara's own record
        sara = payload.get("sara") or {}
        sara_lines = []
        for entry in (sara.get("journal") or [])[:8]:
            sara_lines.append(
                f"- {entry['time']} (my {entry.get('type')} note — a guess I made"
                + (f", feeling {entry['mood']}" if entry.get("mood") else "")
                + f"): {entry.get('content')}"
            )
        for note in (sara.get("notifications") or [])[:10]:
            sara_lines.append(
                f"- {note['time']} I messaged him ({note.get('category')}): "
                f"{note.get('title') or note.get('message')}"
                + (" — he engaged" if note.get("engaged") else "")
            )
        block("My own notes and messages (my read at the time — NOT recorded facts)",
              sara_lines)

        # -- background
        misc = payload.get("misc") or {}
        misc_lines = []
        email = misc.get("email")
        if email:
            misc_lines.append(
                f"- Email: {email.get('received')} received, "
                f"{email.get('high_priority')} high priority, {email.get('read')} read"
            )
        for automation in (misc.get("automations") or [])[:6]:
            misc_lines.append(
                f"- Automation '{automation.get('name')}' ran {automation.get('runs')}x "
                f"({automation.get('successful')} clean)"
            )
        home = misc.get("home")
        if home:
            misc_lines.append(
                f"- Home: {home.get('transitions')} state changes across "
                f"{home.get('entities')} entities (routine background activity)"
            )
        block("Background", misc_lines)

        facts = "\n\n".join(blocks) if blocks else "(No recorded activity for this day.)"
        return self._cap_facts(facts, blocks)

    def _cap_facts(self, facts: str, blocks: List[str]) -> str:
        """Keep the sheet under MAX_FACT_TOKENS by dropping whole low-value
        sections from the bottom up, and saying so rather than truncating
        silently mid-sentence."""
        if estimate_tokens(facts) <= MAX_FACT_TOKENS:
            return facts

        kept = list(blocks)
        dropped: List[str] = []
        # Sections are emitted most-important-first, so drop from the bottom.
        # Stop at one — a single oversized section is better hard-truncated
        # than dropped, which would leave the model an empty sheet.
        while len(kept) > 1 and estimate_tokens("\n\n".join(kept)) > MAX_FACT_TOKENS:
            removed = kept.pop()
            dropped.append(removed.splitlines()[0].lstrip("# ").strip())

        result = "\n\n".join(kept)
        if estimate_tokens(result) > MAX_FACT_TOKENS:
            result = result[: MAX_FACT_TOKENS * CHARS_PER_TOKEN].rstrip() + "\n… (truncated)"
        if dropped:
            result += ("\n\n(Fact sheet trimmed for length; omitted sections: "
                       + ", ".join(reversed(dropped)) + ".)")
        return result

    # ------------------------------------------------------------------
    # 2c. The one LLM call
    # ------------------------------------------------------------------

    # Sections that record something David actually did. Sara's own notes,
    # background email counts and house telemetry do not count — a day with
    # only those is a day with no record of him, and the entry should say so
    # in a few sentences rather than inventing a narrative to fill the page.
    DAVID_EVIDENCE_SECTIONS = ("chat", "fitness", "nutrition", "recovery",
                               "calendar", "tasks", "learning", "notes")

    def _is_thin_day(self, payload: Dict[str, Any]) -> bool:
        for key in self.DAVID_EVIDENCE_SECTIONS:
            value = payload.get(key)
            if key == "calendar":
                # Someone else's appointment is not evidence of David's day.
                if any(entry.get("is_davids") for entry in (value or [])):
                    return False
                continue
            if _has_content(value):
                return False
        return True

    async def write_diary(
        self, facts: str, log_date: date, thin_day: bool = False
    ) -> Optional[str]:
        """One bounded call on the local background lane. No retry loop —
        the regenerate endpoint is the retry."""
        thin_note = (
            "\n- There is almost nothing on record for this day. Write 2-4 "
            "sentences saying plainly that the day left little trace, name only "
            "what IS listed, and stop. Do not fill the gap with atmosphere, "
            "inferred mood, or invented activity."
        ) if thin_day else ""
        prompt = DIARY_PROMPT.format(
            weekday=log_date.strftime("%A"),
            date_long=log_date.strftime("%B %-d, %Y"),
            date_iso=log_date.isoformat(),
            facts=facts,
            thin_note=thin_note,
        )
        try:
            client = get_background_llm_client()
            response = await client.chat_completion(
                messages=[
                    {"role": "system", "content": DIARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=DIARY_MAX_TOKENS,
                request_timeout=DIARY_TIMEOUT_SECONDS,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                caller="daily_log_diary",
            )
            content = (response or {}).get("choices", [{}])[0].get("message", {}).get("content")
            content = (content or "").strip()
            return content or None
        except Exception as e:
            logger.error(f"Daily log: diary generation failed for {log_date}: {e}")
            return None

    # ------------------------------------------------------------------
    # 2d. Orchestration
    # ------------------------------------------------------------------

    async def generate(
        self,
        db: Session,
        user_id: str,
        log_date: date,
        replay: Optional[DayReplay] = None,
    ) -> DailyLogResult:
        """Build the payload, render facts, write the diary, cache both.

        The cache upsert is idempotent, so this doubles as the regenerate and
        backfill path. A failed LLM call still caches the structured replay
        with a NULL summary — never a hard failure.
        """
        if replay is None:
            replay = await day_replay_builder.build_replay(db, user_id, log_date)

        payload = await self.build_payload(db, user_id, log_date, replay=replay)
        facts = self.render_facts(payload)
        diary = await self.write_diary(facts, log_date, thin_day=self._is_thin_day(payload))

        cached = await day_replay_builder.cache_replay(db, replay, summary_text=diary)

        if not cached:
            logger.error(f"Daily log for {log_date} could not be persisted")
        elif diary:
            logger.info(f"📔 Daily log written for {log_date} ({len(diary)} chars)")
        else:
            logger.warning(f"Daily log for {log_date} cached without a diary (LLM unavailable)")

        error = None
        if not cached:
            error = "cache_write_failed"
        elif not diary:
            error = "diary_generation_failed"

        return DailyLogResult(
            log_date=log_date,
            diary=diary,
            payload=payload,
            facts=facts,
            total_events=replay.total_events,
            cached=cached,
            error=error,
        )


# Singleton instance
daily_log_service = DailyLogService()
