from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.models.reminder import Timer
from app.db.session import get_db
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import uuid


class TimersStartTool(BaseTool):
    """Tool for starting new timers"""
    
    @property
    def name(self) -> str:
        return "timers_start"
    
    @property
    def description(self) -> str:
        return "Start a new timer with optional label and duration in minutes. If no duration is provided, creates an open-ended timer."
    
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
                    "description": "Duration in minutes. If not provided, creates an open-ended timer."
                }
            }
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Start a new timer"""
        
        label = kwargs.get("label", "")
        duration = kwargs.get("duration")
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            # Calculate end time
            now = datetime.now(timezone.utc)
            if duration:
                if duration <= 0:
                    return ToolResult(
                        success=False,
                        message="Duration must be a positive number of minutes"
                    )
                ends_at = now + timedelta(minutes=duration)
            else:
                # For open-ended timers, set a far future date
                ends_at = now + timedelta(days=365)  # 1 year from now
            
            # Create timer
            timer = Timer(
                user_id=user_id,
                label=label,
                ends_at=ends_at,
                status="running"
            )
            
            db.add(timer)
            db.commit()
            db.refresh(timer)
            
            message = f"Started timer"
            if label:
                message += f": {label}"
            if duration:
                message += f" ({duration} minutes)"
            else:
                message += " (open-ended)"
            
            return ToolResult(
                success=True,
                data={
                    "timer_id": str(timer.id),
                    "label": timer.label,
                    "ends_at": timer.ends_at.isoformat(),
                    "duration_minutes": duration,
                    "status": timer.status,
                    "created_at": timer.created_at.isoformat()
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
                query = query.filter(Timer.status.in_(["running", "completed"]))
            else:
                query = query.filter(Timer.status == "running")
            
            timers = query.order_by(Timer.created_at.desc()).limit(limit).all()
            
            now = datetime.now(timezone.utc)
            timer_list = []
            
            for timer in timers:
                # Calculate time remaining
                time_remaining = None
                is_expired = False
                
                if timer.status == "running":
                    remaining_seconds = (timer.ends_at - now).total_seconds()
                    if remaining_seconds <= 0:
                        is_expired = True
                        # Auto-complete expired timers
                        timer.status = "completed"
                        db.commit()
                    else:
                        time_remaining = {
                            "total_seconds": int(remaining_seconds),
                            "minutes": int(remaining_seconds // 60),
                            "hours": int(remaining_seconds // 3600)
                        }
                
                timer_data = {
                    "timer_id": str(timer.id),
                    "label": timer.label,
                    "ends_at": timer.ends_at.isoformat(),
                    "status": timer.status,
                    "created_at": timer.created_at.isoformat(),
                    "time_remaining": time_remaining,
                    "is_expired": is_expired
                }
                
                timer_list.append(timer_data)
            
            active_count = len([t for t in timer_list if t["status"] == "running" and not t["is_expired"]])
            
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
            
            if timer.status in ["cancelled", "completed"]:
                return ToolResult(
                    success=False,
                    message=f"Timer is already {timer.status}"
                )
            
            # Cancel the timer
            timer.status = "cancelled"
            db.commit()
            
            message = f"Cancelled timer"
            if timer.label:
                message += f": {timer.label}"
            
            return ToolResult(
                success=True,
                data={
                    "timer_id": str(timer.id),
                    "label": timer.label,
                    "ends_at": timer.ends_at.isoformat(),
                    "status": timer.status
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