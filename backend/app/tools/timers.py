from typing import Dict, Any
# A timer's start/end are naive `timestamp` columns holding UTC; every
# readback goes through civil_time so it is spoken in David's clock (see
# finding 23, and the reminders_list readback that was four hours out).
from app.services.civil_time import as_utc, describe_instant
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy import Column, String, DateTime, Integer, Boolean, func
from sqlalchemy.orm import declarative_base, Session
from datetime import datetime, timezone, timedelta
import uuid

# Define Timer model locally to avoid circular imports
Base = declarative_base()

class Timer(Base):
    __tablename__ = "timer"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    # R05 (Sara repair plan 2026-09-25, evidence
    # D04_TIMERS_STATUS_CRASHES_NAIVE_AWARE_DATETIME): the REAL `timer`
    # table (verified directly against the schema: `\d timer`) has genuinely
    # naive `timestamp without time zone` columns — not a Python-type
    # mismatch with an aware column, as first suspected. `timezone=True`
    # here would not change what the driver hands back for an actual
    # naive-typed column, and would misdescribe the real schema. The naive
    # value IS a UTC instant (TimersStartTool always writes
    # `datetime.now(timezone.utc)`) — it just has no tzinfo attached. Fixed
    # at the comparison site instead (`_as_utc` below), not here.
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


def _as_utc(value: datetime) -> datetime:
    """A value read back from `timer.start_time`/`end_time` is a naive
    datetime whose WALL-CLOCK VALUE is already UTC (every writer in this
    file stores `datetime.now(timezone.utc)` into these naive columns) —
    attach the tzinfo the value already implicitly has, rather than
    comparing it against an aware `datetime.now(timezone.utc)` and raising
    "can't subtract offset-naive and offset-aware datetimes". A value that
    somehow already carries tzinfo (e.g. after a future migration to a real
    timestamptz column) passes through unchanged."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TimersStartTool(BaseTool):
    """Tool for starting new timers"""
    
    @property
    def name(self) -> str:
        return "timers_start"
    
    @property
    def description(self) -> str:
        return "Start a new timer with optional label and duration. Use duration_seconds for precise durations (e.g., 30 seconds, 90 seconds). For longer timers, can use duration in minutes. If no duration is provided, defaults to 25 minutes."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Optional label/description for the timer"
                },
                "duration": {
                    "type": "integer",
                    "description": "Duration in minutes. Deprecated - use duration_seconds for more precision."
                },
                "duration_seconds": {
                    "type": "integer",
                    "description": "Duration in seconds. Takes priority over duration if both provided."
                }
            }
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Start a new timer"""

        title = kwargs.get("label", "Timer")
        duration_seconds = kwargs.get("duration_seconds")
        duration_minutes = kwargs.get("duration", 25)  # Default 25 minutes if not specified

        # Prefer duration_seconds if provided, otherwise use duration in minutes
        if duration_seconds is not None:
            total_seconds = duration_seconds
            duration_display = f"{duration_seconds} seconds" if duration_seconds < 60 else f"{duration_seconds // 60}m {duration_seconds % 60}s"
        else:
            total_seconds = duration_minutes * 60
            duration_display = f"{duration_minutes} minutes"

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Validate duration
            if total_seconds <= 0:
                return ToolResult(
                    success=False,
                    message="Duration must be a positive number"
                )

            # Calculate times
            now = datetime.now(timezone.utc)
            end_time = now + timedelta(seconds=total_seconds)

            # Create timer using correct field names
            timer = Timer(
                user_id=user_id,
                title=title,
                duration_minutes=int(total_seconds / 60),  # Store as minutes for legacy compatibility
                start_time=now,
                end_time=end_time,
                is_active=True,
                is_completed=False
            )

            db.add(timer)
            db.commit()
            db.refresh(timer)

            message = f"Started timer '{title}' for {duration_display}"
            
            return ToolResult(
                success=True,
                data={
                    "timer_id": str(timer.id),
                    "title": timer.title,
                    "end_time": as_utc(timer.end_time).isoformat(),
                    "ends": describe_instant(timer.end_time),
                    "duration_minutes": timer.duration_minutes,
                    "is_active": timer.is_active,
                    "created_at": as_utc(timer.created_at).isoformat() if timer.created_at else None
                },
                message=message
            )
            
        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to start timer: {str(e)}"
            )
        finally:
            db.close()


class TimersStatusTool(BaseTool):
    """Tool for checking timer status"""
    
    @property
    def name(self) -> str:
        return "timers_status"
    
    @property
    def description(self) -> str:
        return "Check the status of all active timers, including time remaining and whether they've completed."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_completed": {
                    "type": "boolean",
                    "description": "Whether to include recently completed timers (default: false)",
                    "default": False
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of timers to return (default: 10)",
                    "default": 10
                }
            }
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Check timer status"""

        include_completed = kwargs.get("include_completed", False)
        limit = kwargs.get("limit", 10)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            query = db.query(Timer).filter(Timer.user_id == user_id)

            if include_completed:
                # Include both active and completed timers
                query = query.filter((Timer.is_active == True) | (Timer.is_completed == True))
            else:
                # Only active (running) timers
                query = query.filter(Timer.is_active == True, Timer.is_completed == False)

            timers = query.order_by(Timer.created_at.desc()).limit(limit).all()

            now = datetime.now(timezone.utc)
            timer_list = []

            for timer in timers:
                # Calculate time remaining
                time_remaining = None
                is_expired = False

                if timer.is_active and not timer.is_completed:
                    remaining_seconds = (_as_utc(timer.end_time) - now).total_seconds()
                    if remaining_seconds <= 0:
                        is_expired = True
                        # Auto-complete expired timers
                        timer.is_active = False
                        timer.is_completed = True
                        db.commit()
                    else:
                        time_remaining = {
                            "total_seconds": int(remaining_seconds),
                            "minutes": int(remaining_seconds // 60),
                            "hours": int(remaining_seconds // 3600)
                        }

                timer_data = {
                    "timer_id": str(timer.id),
                    "title": timer.title,
                    "end_time": as_utc(timer.end_time).isoformat(),
                    "ends": describe_instant(timer.end_time),
                    "is_active": timer.is_active,
                    "is_completed": timer.is_completed,
                    "created_at": as_utc(timer.created_at).isoformat() if timer.created_at else None,
                    "time_remaining": time_remaining,
                    "is_expired": is_expired
                }

                timer_list.append(timer_data)

            active_count = len([t for t in timer_list if t["is_active"] and not t["is_expired"]])

            return ToolResult(
                success=True,
                data={
                    "timers": timer_list,
                    "active_count": active_count,
                    "total_found": len(timer_list)
                },
                message=f"Found {len(timer_list)} timers ({active_count} active)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to check timer status: {str(e)}"
            )
        finally:
            db.close()


class TimersCancelTool(BaseTool):
    """Tool for canceling timers"""
    
    @property
    def name(self) -> str:
        return "timers_cancel"
    
    @property
    def description(self) -> str:
        return "Cancel a running timer by ID. This sets the timer status to 'cancelled'."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timer_id": {
                    "type": "string",
                    "description": "The ID of the timer to cancel"
                }
            },
            "required": ["timer_id"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Cancel a timer"""

        timer_id = kwargs.get("timer_id")

        if not timer_id:
            return ToolResult(
                success=False,
                message="Timer ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Find the timer
            timer = db.query(Timer).filter(
                Timer.id == timer_id,
                Timer.user_id == user_id
            ).first()

            if not timer:
                return ToolResult(
                    success=False,
                    message="Timer not found"
                )

            # Check if already inactive or completed
            if not timer.is_active or timer.is_completed:
                status_desc = "completed" if timer.is_completed else "cancelled"
                return ToolResult(
                    success=False,
                    message=f"Timer is already {status_desc}"
                )

            # Cancel the timer by marking it inactive
            timer.is_active = False
            db.commit()

            message = f"Cancelled timer"
            if timer.title:
                message += f": {timer.title}"

            return ToolResult(
                success=True,
                data={
                    "timer_id": str(timer.id),
                    "title": timer.title,
                    "end_time": as_utc(timer.end_time).isoformat(),
                    "ends": describe_instant(timer.end_time),
                    "is_active": timer.is_active,
                    "is_completed": timer.is_completed
                },
                message=message
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to cancel timer: {str(e)}"
            )
        finally:
            db.close()