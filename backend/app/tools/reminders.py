from typing import Dict, Any
from app.services.civil_time import (
    AmbiguousTimeError,
    TIME_PARAMETER_CONTRACT,
    as_utc,
    describe_instant,
    parse_user_datetime,
)
from app.tools.base import BaseTool, ToolResult
from app.models.reminder import Reminder
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, date
import logging
import uuid

logger = logging.getLogger(__name__)


class RemindersCreateTool(BaseTool):
    """Tool for creating new reminders"""

    @property
    def name(self) -> str:
        return "reminders_create"

    @property
    def description(self) -> str:
        return (
            "Create a new reminder with a title and due date/time. "
            "reminder_time is ISO 8601; a time with no offset means David's own "
            "local clock, not UTC."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The reminder title/message"
                },
                "description": {
                    "type": "string",
                    "description": "Optional longer description"
                },
                "reminder_time": {
                    "type": "string",
                    "description": (
                        "When the reminder should trigger. "
                        + TIME_PARAMETER_CONTRACT
                    ),
                },
                "confirm_time": {
                    "type": "boolean",
                    "description": "Set true only when David explicitly asked for this exact time, to override a schedule-conflict warning."
                }
            },
            "required": ["title", "reminder_time"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new reminder"""

        title = kwargs.get("title")
        description = kwargs.get("description", "")
        reminder_time_str = kwargs.get("reminder_time")

        if not title:
            return ToolResult(
                success=False,
                message="Reminder title is required"
            )

        if not reminder_time_str:
            return ToolResult(
                success=False,
                message="Reminder time is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # One timestamp contract, shared with timers and the calendar —
            # see app/services/civil_time.py. This used to read a naive
            # timestamp as UTC while the calendar read the identical string as
            # local (finding 37), so the same model output in the same turn
            # meant two instants four hours apart, and a 7pm reminder was
            # booked for 3pm (finding 16).
            try:
                _interpretation = parse_user_datetime(reminder_time_str)
            except AmbiguousTimeError as exc:
                return ToolResult(success=False, message=str(exc))
            reminder_time = _interpretation.instant
            _time_note = _interpretation.note

            # H3 (Brain Alignment): consult David's stated life facts before
            # committing a time on his behalf. A reminder that lands after he's
            # left for work or inside his gym block is flagged so the LLM
            # re-picks — unless it explicitly passes confirm_time=true (David
            # asked for that exact time).
            if not kwargs.get("confirm_time"):
                try:
                    from app.core.timezone import to_local
                    from app.services.life_facts import check_schedule_conflict, describe_day
                    from app.db.session import get_async_session_factory
                    local_when = to_local(reminder_time)
                    async with get_async_session_factory()() as _lf_db:
                        conflict = await check_schedule_conflict(_lf_db, str(user_id), local_when)
                        day_note = await describe_day(_lf_db, str(user_id), local_when.date()) if conflict else None
                    if conflict:
                        return ToolResult(
                            success=False,
                            data={"schedule_conflict": conflict, "day": day_note},
                            message=(
                                f"That time conflicts with a fixed part of David's day: {conflict} "
                                f"{('(' + day_note + ') ') if day_note else ''}"
                                "Pick a time that avoids it. If David explicitly asked for this exact "
                                "time, call again with confirm_time=true."
                            ),
                        )
                except Exception as e:
                    logger.debug(f"life_fact conflict check skipped: {e}")

            reminder = Reminder(
                user_id=user_id,
                title=title,
                description=description,
                reminder_time=reminder_time,
                is_completed=False,
            )

            db.add(reminder)
            # reminder.id's default is a Python callable, but SQLAlchemy
            # only resolves Column defaults at flush time — without this,
            # reminder.id is still None here and every event below got
            # dedupe_key "reminder-created:None", colliding across every
            # reminder ever created in one dedupe row.
            db.flush()

            # Living-world-context plan: reminders were modeled in the
            # catalog/reducer (open_threads domain, due_at tracked) but had
            # no real producer — goal_manager's own attempt called
            # event_bus.publish() with a plain dict, which record_legacy_
            # event can't read (needs an Event with .event_type), and only
            # fires when an event_bus instance was actually wired in (it
            # defaults to None). Same-transaction, atomic with the reminder
            # row, matching every other producer in this codebase.
            from app.services.world_state.writer import append_world_event
            append_world_event(
                db, user_id=str(user_id), kind="reminder.created", source="reminders_tool",
                source_ref=f"reminder:{reminder.id}", aggregate_type="reminder", aggregate_id=str(reminder.id),
                actor_type="assistant", correlation_id=str(reminder.id),
                dedupe_key=f"reminder-created:{reminder.id}",
                occurred_at=reminder_time,
                payload={
                    "reminder_id": str(reminder.id), "title": title,
                    "due_at": reminder_time.isoformat(),
                    "description": description,
                },
            )

            db.commit()
            db.refresh(reminder)

            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "reminder_time": reminder.reminder_time.isoformat(),
                    "is_completed": reminder.is_completed,
                    "created_at": reminder.created_at.isoformat(),
                    # The readback is in David's own clock, always with the
                    # zone — a readback that reads as a different hour than
                    # what he asked for is the whole of finding 16.
                    "when": describe_instant(reminder.reminder_time),
                },
                message=(
                    f"Created reminder: {title[:50]}{'...' if len(title) > 50 else ''}"
                    f" for {describe_instant(reminder.reminder_time)}"
                    + (f" — {_time_note}" if _time_note else "")
                ),
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create reminder: {str(e)}"
            )
        finally:
            db.close()


class RemindersListTool(BaseTool):
    """Tool for listing reminders"""

    @property
    def name(self) -> str:
        return "reminders_list"

    @property
    def description(self) -> str:
        return "List reminders for a specific day or all upcoming reminders. Can filter by completion status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional date to filter reminders (YYYY-MM-DD format). If not provided, shows all upcoming reminders."
                },
                "include_completed": {
                    "type": "boolean",
                    "description": "Include completed reminders (default: false)",
                    "default": False
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of reminders to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List reminders"""

        date_str = kwargs.get("date")
        include_completed = kwargs.get("include_completed", False)
        limit = kwargs.get("limit", 20)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            query = db.query(Reminder).filter(Reminder.user_id == user_id)

            if not include_completed:
                query = query.filter(Reminder.is_completed == False)

            # Filter by date if provided
            if date_str:
                try:
                    filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    start_of_day = datetime.combine(filter_date, datetime.min.time(), timezone.utc)
                    end_of_day = datetime.combine(filter_date, datetime.max.time(), timezone.utc)

                    query = query.filter(
                        and_(
                            Reminder.reminder_time >= start_of_day,
                            Reminder.reminder_time <= end_of_day
                        )
                    )
                except ValueError:
                    return ToolResult(
                        success=False,
                        message="Invalid date format. Please use YYYY-MM-DD format."
                    )
            else:
                # Show upcoming reminders only
                if not include_completed:
                    query = query.filter(Reminder.reminder_time >= datetime.now(timezone.utc))

            reminders = query.order_by(Reminder.reminder_time).limit(limit).all()

            reminder_list = []
            for reminder in reminders:
                # `reminder_time` is a naive `timestamp` column holding UTC, so
                # `.isoformat()` produced "2026-10-01T21:00:00" — an offsetless
                # string the model read as 9:00 PM when the reminder was in fact
                # set for 5:00 PM his time. Found live on the acceptance trial:
                # the create was correct and the READBACK was four hours out,
                # which is finding 16's other half. Every field that leaves here
                # now carries its zone, and `when` is the phrasing to speak.
                _when_utc = as_utc(reminder.reminder_time)
                reminder_list.append({
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "description": reminder.description or "",
                    "reminder_time": _when_utc.isoformat() if _when_utc else None,
                    "when": describe_instant(_when_utc) if _when_utc else None,
                    "is_completed": bool(reminder.is_completed),
                    "created_at": (
                        as_utc(reminder.created_at).isoformat()
                        if reminder.created_at else None
                    ),
                })

            message = f"Found {len(reminder_list)} reminders"
            if date_str:
                message += f" for {date_str}"
            if reminder_list:
                message += ": " + "; ".join(
                    f"{r['title']} — {r['when']}"
                    + (" (done)" if r["is_completed"] else "")
                    for r in reminder_list[:10]
                )

            return ToolResult(
                success=True,
                data={
                    "reminders": reminder_list,
                    "date": date_str,
                    "total_found": len(reminder_list)
                },
                message=message
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list reminders: {str(e)}"
            )
        finally:
            db.close()


class RemindersCancelTool(BaseTool):
    """Tool for canceling/completing reminders"""

    @property
    def name(self) -> str:
        return "reminders_cancel"

    @property
    def description(self) -> str:
        return "Cancel or complete a reminder by ID. Marks it as completed."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The ID of the reminder to cancel/complete"
                }
            },
            "required": ["reminder_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Cancel a reminder by marking it completed"""

        reminder_id = kwargs.get("reminder_id")

        if not reminder_id:
            return ToolResult(
                success=False,
                message="Reminder ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id,
                Reminder.user_id == user_id
            ).first()

            if not reminder:
                return ToolResult(
                    success=False,
                    message="Reminder not found"
                )

            if reminder.is_completed:
                return ToolResult(
                    success=False,
                    message="Reminder is already completed"
                )

            reminder.is_completed = True

            from app.services.world_state.writer import append_world_event
            append_world_event(
                db, user_id=str(user_id), kind="reminder.completed", source="reminders_tool",
                source_ref=f"reminder:{reminder.id}", aggregate_type="reminder", aggregate_id=str(reminder.id),
                actor_type="assistant", correlation_id=str(reminder.id),
                dedupe_key=f"reminder-completed:{reminder.id}",
                payload={"reminder_id": str(reminder.id), "title": reminder.title},
            )

            db.commit()

            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "reminder_time": as_utc(reminder.reminder_time).isoformat(),
                    "when": describe_instant(reminder.reminder_time),
                    "is_completed": True
                },
                message=(
                    f"Cancelled reminder: {reminder.title[:50]}"
                    f"{'...' if len(reminder.title) > 50 else ''}"
                    f" (was {describe_instant(reminder.reminder_time)})"
                )
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to cancel reminder: {str(e)}"
            )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Reschedule and update — reliable-assistant plan Phase C4
# ---------------------------------------------------------------------------
#
# "Expose coherent operations such as reschedule reminder… Do not require the
# model to improvise coupled delete/create sequences."
#
# Before this there was no way to change a reminder at all: the registry had
# `reminders_create`, `reminders_list` and `reminders_cancel` and nothing else.
# "Move the vet one to seven" therefore had exactly two available shapes, and
# both are confirmed findings:
#
#   * cancel + create — which is finding 28's mechanism ("a compensating undo
#     request created a brand-new duplicate reminder rather than truly
#     restoring the original", and the action_ledger's own bookkeeping was
#     never updated), and destroys the reminder's identity, so a later "is it
#     still scheduled?" resolves to a row that no longer exists;
#   * nothing — and Sara says she moved it anyway.
#
# One row, one identity, one transaction. The delivery state is reset in the
# SAME update, because that is the part a cancel+create accidentally got right
# and a naive UPDATE gets wrong: a reminder that already fired, or that a
# worker has claimed, must become deliverable again at its new time or the
# reschedule is a lie (see app/tasks/inproc_schedulers.py — the predispatch
# query skips any row with a terminal `notified_at`).

_DELIVERY_RESET = {
    "notified_at": None,
    "delivery_status": None,
    "claimed_at": None,
    "delivery_attempts": 0,
    "last_error": None,
}


class RemindersRescheduleTool(BaseTool):
    """Move an existing reminder to a new time, keeping its identity."""

    @property
    def name(self) -> str:
        return "reminders_reschedule"

    @property
    def description(self) -> str:
        return (
            "Move an existing reminder to a different time — 'move the vet one to "
            "seven', 'push the dentist reminder to Friday', 'make it an hour later'. "
            "Use THIS instead of cancelling and creating a new one: cancel+create "
            "gives the reminder a new id, so a later 'is it still scheduled?' can't "
            "find what you changed, and it leaves the cancelled row behind looking "
            "like a duplicate. Keeps the same reminder, and makes it deliverable "
            "again at the new time even if the old time already passed. "
            "Find the reminder first (reminders_list) and pass its real id."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The reminder to move (from reminders_list).",
                },
                "reminder_time": {
                    "type": "string",
                    "description": "The new time. " + TIME_PARAMETER_CONTRACT,
                },
            },
            "required": ["reminder_id", "reminder_time"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        reminder_id = kwargs.get("reminder_id")
        new_time_str = kwargs.get("reminder_time")
        if not reminder_id:
            return ToolResult(success=False, message="reminder_id is required.")
        if not new_time_str:
            return ToolResult(success=False, message="reminder_time is required.")

        try:
            interpretation = parse_user_datetime(new_time_str)
        except AmbiguousTimeError as exc:
            return ToolResult(success=False, message=str(exc))

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id, Reminder.user_id == user_id,
            ).first()
            if not reminder:
                return ToolResult(success=False, message="Reminder not found.")

            # `reminder.reminder_time` is a naive `timestamp` column (the
            # model's `timezone=True` notwithstanding) — comparing it to an
            # aware instant raises TypeError, which is finding 23's exact
            # mechanism in `timers_status`.
            old_time = as_utc(reminder.reminder_time)
            if old_time is not None and abs(
                (old_time - interpretation.instant).total_seconds()
            ) < 60:
                return ToolResult(
                    success=False,
                    message=(
                        f"\"{reminder.title}\" is already set for "
                        f"{describe_instant(interpretation.instant)} — nothing to move."
                    ),
                )

            was_completed = bool(reminder.is_completed)
            reminder.reminder_time = interpretation.instant
            # Moving a reminder un-completes it: a completed reminder with a
            # future time would never be delivered, so silently leaving the
            # flag set is the same class of lie as not moving it at all.
            reminder.is_completed = False
            for field, value in _DELIVERY_RESET.items():
                setattr(reminder, field, value)

            try:
                from app.services.world_state.writer import append_world_event
                append_world_event(
                    db, user_id=str(user_id), kind="reminder.rescheduled",
                    source="reminders_tool", source_ref=f"reminder:{reminder.id}",
                    aggregate_type="reminder", aggregate_id=str(reminder.id),
                    actor_type="assistant", correlation_id=str(reminder.id),
                    dedupe_key=(
                        f"reminder-rescheduled:{reminder.id}:"
                        f"{interpretation.instant.isoformat()}"
                    ),
                    payload={
                        "reminder_id": str(reminder.id), "title": reminder.title,
                        "from": old_time.isoformat() if old_time else None,
                        "to": interpretation.instant.isoformat(),
                    },
                )
            except Exception as event_err:
                logger.warning(f"reminder.rescheduled event skipped: {event_err}")

            db.commit()

            parts = [
                f"Moved \"{reminder.title}\" to {describe_instant(interpretation.instant)}"
            ]
            if old_time is not None:
                parts.append(f"(was {describe_instant(old_time)})")
            if was_completed:
                parts.append("— it had been marked done, so it's active again")
            if interpretation.note:
                parts.append(f"— {interpretation.note}")
            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "reminder_time": interpretation.instant.isoformat(),
                    "when": describe_instant(interpretation.instant),
                    "previous_time": old_time.isoformat() if old_time else None,
                    "reactivated": was_completed,
                },
                message=" ".join(parts) + ".",
            )
        except Exception as e:
            db.rollback()
            logger.error(f"reminders_reschedule failed: {type(e).__name__}: {e}")
            return ToolResult(success=False, message=f"Failed to move the reminder: {e}")
        finally:
            db.close()


class RemindersUpdateTool(BaseTool):
    """Change what an existing reminder SAYS, without touching its time."""

    @property
    def name(self) -> str:
        return "reminders_update"

    @property
    def description(self) -> str:
        return (
            "Change an existing reminder's wording — 'make it say call the vet about "
            "the vaccination', 'add that it's the back door key'. Does not change "
            "when it fires; use reminders_reschedule for that. Use this rather than "
            "creating a second reminder, which leaves David with two."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "The reminder to change."},
                "title": {"type": "string", "description": "New title, if it should change."},
                "description": {
                    "type": "string",
                    "description": "New longer description, if it should change.",
                },
            },
            "required": ["reminder_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        reminder_id = kwargs.get("reminder_id")
        new_title = kwargs.get("title")
        new_description = kwargs.get("description")
        if not reminder_id:
            return ToolResult(success=False, message="reminder_id is required.")
        if new_title is None and new_description is None:
            return ToolResult(
                success=False,
                message="Nothing to change — pass a new title or description.",
            )

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id, Reminder.user_id == user_id,
            ).first()
            if not reminder:
                return ToolResult(success=False, message="Reminder not found.")

            changed = []
            if new_title is not None and new_title.strip() and new_title != reminder.title:
                reminder.title = new_title.strip()
                changed.append("title")
            if new_description is not None and new_description != (reminder.description or ""):
                reminder.description = new_description
                changed.append("description")
            if not changed:
                return ToolResult(
                    success=False,
                    message=f"\"{reminder.title}\" already says that — nothing changed.",
                )
            db.commit()
            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "description": reminder.description,
                    "changed": changed,
                    "when": describe_instant(reminder.reminder_time)
                    if reminder.reminder_time else None,
                },
                message=(
                    f"Updated the {' and '.join(changed)} — it now reads "
                    f"\"{reminder.title}\", still set for "
                    f"{describe_instant(reminder.reminder_time) if reminder.reminder_time else 'no time'}."
                ),
            )
        except Exception as e:
            db.rollback()
            logger.error(f"reminders_update failed: {type(e).__name__}: {e}")
            return ToolResult(success=False, message=f"Failed to update the reminder: {e}")
        finally:
            db.close()
