"""
Training Schedule Tool
Allows Sara to change which days of the week are training days
by updating template scheduled_days and toggling individual dates.
"""
from app.tools.base import BaseTool, ToolResult
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db
from datetime import date, datetime, timedelta
import json
import uuid


VALID_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


class TrainingScheduleTool(BaseTool):
    """Change training day schedule — swap days, toggle specific dates, view schedule"""

    @property
    def name(self) -> str:
        return "training_schedule"

    @property
    def description(self) -> str:
        return """Manage the weekly training schedule. Use this when the user wants to:
- Swap training days (e.g. "move Tuesday workouts to Friday")
- See which days are currently scheduled
- Toggle a specific date as training or rest day
- Change which days of the week a workout template runs on

Actions:
  "view"   — show current schedule (all templates with their scheduled_days)
  "swap"   — replace one weekday with another across all templates (e.g. swap tuesday→friday)
  "toggle" — flip a specific date between training/rest day
  "set"    — set a template's scheduled_days to an exact list"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["view", "swap", "toggle", "set"],
                    "description": "What to do"
                },
                "from_day": {
                    "type": "string",
                    "description": "Day to remove (for swap). Lowercase weekday name."
                },
                "to_day": {
                    "type": "string",
                    "description": "Day to add (for swap). Lowercase weekday name."
                },
                "target_date": {
                    "type": "string",
                    "description": "Specific date to toggle (YYYY-MM-DD format, for toggle action)"
                },
                "template_name": {
                    "type": "string",
                    "description": "Template to target (for set action). Partial match supported."
                },
                "scheduled_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact list of weekdays (for set action)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, user_id: str, action: str = "view",
                      from_day: str = None, to_day: str = None,
                      target_date: str = None, template_name: str = None,
                      scheduled_days: list = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            if action == "view":
                return self._view_schedule(db, user_id)
            elif action == "swap":
                return self._swap_days(db, user_id, from_day, to_day)
            elif action == "toggle":
                return self._toggle_date(db, user_id, target_date)
            elif action == "set":
                return self._set_schedule(db, user_id, template_name, scheduled_days)
            else:
                return ToolResult(success=False, message=f"Unknown action: {action}", data=None)
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed: {str(e)}", data=None)
        finally:
            db.close()

    def _view_schedule(self, db: Session, user_id: str) -> ToolResult:
        rows = db.execute(text("""
            SELECT t.id, t.name, t.scheduled_days, p.name as phase_name, p.status as phase_status
            FROM fitness_template t
            LEFT JOIN fitness_phase p ON t.phase_id = p.id
            WHERE t.user_id = :uid
            ORDER BY p.status = 'active' DESC NULLS LAST, t.name
        """), {"uid": user_id}).fetchall()

        templates = []
        for row in rows:
            r = dict(row._mapping)
            days = r["scheduled_days"]
            if isinstance(days, str):
                days = json.loads(days)
            templates.append({
                "id": r["id"],
                "name": r["name"],
                "scheduled_days": days or [],
                "phase": r["phase_name"],
                "phase_status": r["phase_status"],
            })

        return ToolResult(
            success=True,
            message=f"Found {len(templates)} template(s) with their schedules",
            data={"templates": templates}
        )

    def _swap_days(self, db: Session, user_id: str, from_day: str, to_day: str) -> ToolResult:
        if not from_day or not to_day:
            return ToolResult(success=False, message="Both from_day and to_day are required for swap", data=None)

        from_day = from_day.lower().strip()
        to_day = to_day.lower().strip()

        if from_day not in VALID_DAYS or to_day not in VALID_DAYS:
            return ToolResult(success=False, message=f"Invalid day names. Use: {', '.join(sorted(VALID_DAYS))}", data=None)

        # Get all templates for active phases
        rows = db.execute(text("""
            SELECT t.id, t.name, t.scheduled_days
            FROM fitness_template t
            JOIN fitness_phase p ON t.phase_id = p.id
            WHERE t.user_id = :uid AND p.status = 'active'
        """), {"uid": user_id}).fetchall()

        updated = []
        for row in rows:
            r = dict(row._mapping)
            days = r["scheduled_days"]
            if isinstance(days, str):
                days = json.loads(days)
            if not days:
                continue

            if from_day in days:
                new_days = [to_day if d == from_day else d for d in days]
                db.execute(text("""
                    UPDATE fitness_template SET scheduled_days = :days, updated_at = NOW()
                    WHERE id = :id AND user_id = :uid
                """), {"days": json.dumps(new_days), "id": r["id"], "uid": user_id})
                updated.append({"template": r["name"], "old_days": days, "new_days": new_days})

        if not updated:
            return ToolResult(
                success=True,
                message=f"No active templates have {from_day} in their schedule — nothing to swap",
                data={"updated": []}
            )

        # Also update any future workout_sessions: move sessions from from_day to to_day
        today = date.today()
        # Get day-of-week numbers (0=Monday)
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        from_dow = day_names.index(from_day)
        to_dow = day_names.index(to_day)

        future_sessions = db.execute(text("""
            SELECT id, session_date FROM workout_session
            WHERE user_id = :uid AND session_date > :today AND status = 'planned'
              AND EXTRACT(DOW FROM session_date) = :from_dow_pg
        """), {"uid": user_id, "today": today, "from_dow_pg": (from_dow + 1) % 7}).fetchall()
        # PostgreSQL DOW: 0=Sunday, 1=Monday — convert

        sessions_moved = 0
        for sess in future_sessions:
            old_date = sess.session_date
            # Calculate offset to move from from_day to to_day
            diff = (to_dow - from_dow) % 7
            if diff == 0:
                continue
            new_date = old_date + timedelta(days=diff)
            db.execute(text("""
                UPDATE workout_session SET session_date = :new_date, updated_at = NOW()
                WHERE id = :id AND user_id = :uid
            """), {"new_date": new_date, "id": sess.id, "uid": user_id})
            sessions_moved += 1

        db.commit()

        return ToolResult(
            success=True,
            message=f"Swapped {from_day} → {to_day} in {len(updated)} template(s). Moved {sessions_moved} future session(s).",
            data={"updated": updated, "sessions_moved": sessions_moved}
        )

    def _toggle_date(self, db: Session, user_id: str, target_date: str) -> ToolResult:
        if not target_date:
            return ToolResult(success=False, message="target_date is required for toggle", data=None)

        d = date.fromisoformat(target_date)

        existing = db.execute(text("""
            SELECT id FROM workout_session
            WHERE user_id = :uid AND session_date = :d
            LIMIT 1
        """), {"uid": user_id, "d": d}).fetchone()

        if existing:
            db.execute(text("""
                DELETE FROM workout_session WHERE user_id = :uid AND session_date = :d
            """), {"uid": user_id, "d": d})
            db.commit()
            return ToolResult(
                success=True,
                message=f"{target_date} is now a rest day",
                data={"date": target_date, "is_training_day": False}
            )
        else:
            session_id = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO workout_session (id, user_id, session_date, status, created_at, updated_at)
                VALUES (:id, :uid, :d, 'planned', NOW(), NOW())
            """), {"id": session_id, "uid": user_id, "d": d})
            db.commit()
            return ToolResult(
                success=True,
                message=f"{target_date} is now a training day",
                data={"date": target_date, "is_training_day": True}
            )

    def _set_schedule(self, db: Session, user_id: str, template_name: str, scheduled_days: list) -> ToolResult:
        if not template_name:
            return ToolResult(success=False, message="template_name is required for set action", data=None)
        if not scheduled_days:
            return ToolResult(success=False, message="scheduled_days list is required for set action", data=None)

        # Validate days
        normalized = [d.lower().strip() for d in scheduled_days]
        invalid = [d for d in normalized if d not in VALID_DAYS]
        if invalid:
            return ToolResult(success=False, message=f"Invalid days: {invalid}. Use: {', '.join(sorted(VALID_DAYS))}", data=None)

        row = db.execute(text("""
            SELECT id, name, scheduled_days FROM fitness_template
            WHERE user_id = :uid AND LOWER(name) LIKE LOWER(:pattern)
            LIMIT 1
        """), {"uid": user_id, "pattern": f"%{template_name}%"}).fetchone()

        if not row:
            return ToolResult(success=False, message=f"No template matching '{template_name}'", data=None)

        old_days = row.scheduled_days
        if isinstance(old_days, str):
            old_days = json.loads(old_days)

        db.execute(text("""
            UPDATE fitness_template SET scheduled_days = :days, updated_at = NOW()
            WHERE id = :id AND user_id = :uid
        """), {"days": json.dumps(normalized), "id": row.id, "uid": user_id})
        db.commit()

        return ToolResult(
            success=True,
            message=f"Updated '{row.name}' schedule: {old_days} → {normalized}",
            data={"template_id": row.id, "old_days": old_days, "new_days": normalized}
        )
