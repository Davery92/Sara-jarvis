"""Habit tracking routes."""
import json
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.db.session import get_db
from app.models.user import User
from app.models.habit import Habit, HabitItem, HabitInstance, HabitLog, HabitStreak, HabitLink
from app.schemas.habits import (
    HabitCreate, HabitResponse, HabitItemCreate, HabitItemResponse,
    HabitInstanceResponse, HabitTodayStats, HabitTodayResponse,
    HabitLogCreate, HabitStreakResponse, HabitLinkCreate, HabitLinkResponse,
    HabitPauseRequest, HabitInsightsResponse, HabitInsightsOverview,
    HabitInsightsWeeklyStats, HabitInsightsPerformance, HabitInsightsPatterns
)
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/habits", tags=["Habits"])


def habit_to_response(habit: Habit) -> HabitResponse:
    """Convert habit model to response schema."""
    return HabitResponse(
        id=habit.id,
        title=habit.title,
        type=habit.type,
        target_numeric=habit.target_numeric,
        unit=habit.unit,
        rrule=habit.rrule,
        weekly_minimum=habit.weekly_minimum,
        monthly_minimum=habit.monthly_minimum,
        windows=habit.windows,
        checklist_mode=habit.checklist_mode,
        checklist_threshold=habit.checklist_threshold,
        grace_days=habit.grace_days,
        retro_hours=habit.retro_hours,
        paused=bool(habit.paused),
        pause_from=habit.pause_from.isoformat() if habit.pause_from else None,
        pause_to=habit.pause_to.isoformat() if habit.pause_to else None,
        notes=habit.notes,
        created_at=habit.created_at.isoformat(),
        updated_at=habit.updated_at.isoformat()
    )


@router.post("", response_model=HabitResponse)
def create_habit(
    habit_data: HabitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new habit."""
    habit = Habit(
        user_id=current_user.id,
        title=habit_data.title,
        type=habit_data.type,
        target_numeric=habit_data.target_numeric,
        unit=habit_data.unit,
        rrule=habit_data.rrule,
        weekly_minimum=habit_data.weekly_minimum,
        monthly_minimum=habit_data.monthly_minimum,
        windows=habit_data.windows,
        checklist_mode=habit_data.checklist_mode,
        checklist_threshold=habit_data.checklist_threshold,
        grace_days=habit_data.grace_days,
        retro_hours=habit_data.retro_hours,
        notes=habit_data.notes,
        current_streak=0,
        best_streak=0
    )
    db.add(habit)
    db.commit()
    db.refresh(habit)

    # Initialize streak record
    streak = HabitStreak(habit_id=habit.id)
    db.add(streak)
    db.commit()

    return habit_to_response(habit)


@router.get("", response_model=List[HabitResponse])
def list_habits(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all habits for the current user."""
    habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
    return [habit_to_response(habit) for habit in habits]


@router.get("/today", response_model=HabitTodayResponse)
def get_today_habits(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get today's habit instances with stats."""
    from app.services.habit_instances import HabitInstanceGenerator

    # Generate any missing instances for today
    today = datetime.now().date()
    HabitInstanceGenerator.generate_instances_for_all_habits(
        db, current_user.id, today, today
    )

    # Get today's instances
    instances = HabitInstanceGenerator.get_today_instances(db, current_user.id, today)

    # Convert to response format
    habits = [
        HabitInstanceResponse(
            id=instance["instance_id"],
            habit_id=instance["habit_id"],
            date=instance["date"],
            window=instance.get("window"),
            expected=instance["expected"],
            status=instance["status"],
            progress=instance["progress"],
            total_amount=instance.get("total_amount"),
            target=instance.get("target"),
            title=instance["title"],
            type=instance["type"],
            unit=instance.get("unit")
        ) for instance in instances
    ]

    # Calculate stats
    total = len(habits)
    completed = len([h for h in habits if h.status == "complete"])
    in_progress = len([h for h in habits if h.status == "in_progress" or (h.progress > 0 and h.status != "complete")])
    completion_rate = (completed / total * 100) if total > 0 else 0

    stats = HabitTodayStats(
        total=total,
        completed=completed,
        in_progress=in_progress,
        completion_rate=completion_rate
    )

    return HabitTodayResponse(
        date=today.isoformat(),
        habits=habits,
        stats=stats
    )


@router.get("/{habit_id}/streak", response_model=HabitStreakResponse)
def get_habit_streak(
    habit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get streak information for a habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    streak = db.query(HabitStreak).filter(HabitStreak.habit_id == habit_id).first()

    if not streak:
        streak = HabitStreak(habit_id=habit_id)
        db.add(streak)
        db.commit()

    return HabitStreakResponse(
        habit_id=streak.habit_id,
        current_streak=streak.current_streak,
        best_streak=streak.best_streak,
        last_completed=streak.last_completed.isoformat() if streak.last_completed else None
    )


@router.post("/{habit_id}/log")
def log_habit_completion(
    habit_id: str,
    log_data: HabitLogCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Log a habit completion."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    # Create log entry
    log = HabitLog(
        habit_id=habit_id,
        user_id=current_user.id,
        source=log_data.source,
        payload=json.dumps({"amount": log_data.amount}) if log_data.amount else log_data.payload
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Update habit instance progress and streak
    from app.services.habit_instances import HabitInstanceGenerator
    from app.services.habit_streaks import HabitStreakCalculator

    today = date.today()
    instance_data = HabitInstanceGenerator.get_instance_by_habit_and_date(
        db, habit_id, today
    )

    if instance_data:
        # Get all logs for this habit today
        today_logs = db.query(HabitLog).filter(
            HabitLog.habit_id == habit_id,
            HabitLog.ts >= datetime.combine(today, datetime.min.time()),
            HabitLog.ts < datetime.combine(today + timedelta(days=1), datetime.min.time())
        ).all()

        log_dicts = [
            {"payload": l.payload, "ts": l.ts, "source": l.source}
            for l in today_logs
        ]

        # Get checklist items if needed
        checklist_items = []
        if habit.type == "checklist":
            items = db.query(HabitItem).filter(HabitItem.habit_id == habit_id).all()
            checklist_items = [{"id": item.id, "label": item.label} for item in items]

        # Update instance progress
        HabitInstanceGenerator.update_instance_progress(
            db, instance_data["instance_id"], log_dicts, habit, checklist_items
        )

        # Update streak if habit is now complete
        from app.services.habit_progress import HabitProgressCalculator
        is_complete = HabitProgressCalculator.is_habit_complete(
            habit.type, log_dicts, habit.target_numeric, checklist_items,
            habit.checklist_mode or "all", habit.checklist_threshold or 1.0
        )

        if is_complete:
            streak = db.query(HabitStreak).filter(HabitStreak.habit_id == habit_id).first()
            if streak:
                vacation_periods = []
                if habit.pause_from and habit.pause_to:
                    vacation_periods = [(habit.pause_from.date(), habit.pause_to.date())]

                new_current, new_best, last_completed = HabitStreakCalculator.update_streak_after_completion(
                    streak.current_streak,
                    streak.best_streak,
                    streak.last_completed,
                    today,
                    habit.grace_days,
                    vacation_periods
                )

                streak.current_streak = new_current
                streak.best_streak = new_best
                streak.last_completed = last_completed
                streak.updated_at = datetime.now()
                db.commit()

    if app_settings.temerant_enabled and app_settings.temerant_auto_ingestion_enabled:
        try:
            from app.services.temerant import CharacterService, IngestionService
            from app.services.temerant.rules_engine import TemerantRulesEngine

            character = CharacterService.get_character(db, current_user.id)
            if character:
                inferred_action = TemerantRulesEngine.infer_action_type(habit.title, fallback="study")
                IngestionService.log_external_action(
                    db=db,
                    user_id=current_user.id,
                    character=character,
                    source_type="habit",
                    source_ref_id=log.id,
                    mapping_ref=habit.id,
                    default_action_type=inferred_action,
                    action_label=habit.title,
                    notes=None,
                    quantity=log_data.amount,
                    occurred_at=log.ts,
                    metadata={"habit_id": habit.id, "habit_type": habit.type},
                )
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Temerant auto-ingestion failed for habit log")

    return {"message": "Habit logged successfully", "log_id": log.id}


@router.patch("/{habit_id}", response_model=HabitResponse)
def update_habit(
    habit_id: str,
    habit_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    update_fields = [
        "title", "target_numeric", "unit", "rrule", "weekly_minimum",
        "monthly_minimum", "windows", "checklist_mode", "checklist_threshold",
        "grace_days", "retro_hours", "notes"
    ]

    for field in update_fields:
        if field in habit_data:
            setattr(habit, field, habit_data[field])

    habit.updated_at = datetime.now()
    db.commit()
    db.refresh(habit)

    return habit_to_response(habit)


@router.delete("/{habit_id}")
def delete_habit(
    habit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a habit and all associated data."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    # Delete associated data explicitly
    db.query(HabitInstance).filter(HabitInstance.habit_id == habit_id).delete()
    db.query(HabitLog).filter(HabitLog.habit_id == habit_id).delete()
    db.query(HabitStreak).filter(HabitStreak.habit_id == habit_id).delete()
    db.query(HabitItem).filter(HabitItem.habit_id == habit_id).delete()
    db.query(HabitLink).filter(HabitLink.habit_id == habit_id).delete()

    db.delete(habit)
    db.commit()

    return {"message": "Habit deleted successfully"}


@router.post("/{habit_id}/pause")
def pause_habit(
    habit_id: str,
    pause_data: HabitPauseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Pause a habit for a specific period."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    try:
        pause_from = datetime.fromisoformat(pause_data.pause_from)
        pause_to = datetime.fromisoformat(pause_data.pause_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if pause_from >= pause_to:
        raise HTTPException(status_code=400, detail="Pause start must be before pause end")

    habit.paused = 1
    habit.pause_from = pause_from
    habit.pause_to = pause_to
    habit.updated_at = datetime.now()

    db.commit()

    return {"message": f"Habit paused from {pause_from.date()} to {pause_to.date()}"}


@router.post("/{habit_id}/resume")
def resume_habit(
    habit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resume a paused habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    habit.paused = 0
    habit.pause_from = None
    habit.pause_to = None
    habit.updated_at = datetime.now()

    db.commit()

    return {"message": "Habit resumed successfully"}


@router.post("/{habit_id}/items", response_model=HabitItemResponse)
def add_habit_item(
    habit_id: str,
    item_data: HabitItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a checklist item to a habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id,
        Habit.type == "checklist"
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found or not a checklist")

    item = HabitItem(
        habit_id=habit_id,
        label=item_data.label,
        sort_order=item_data.sort_order
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return HabitItemResponse(
        id=item.id,
        habit_id=item.habit_id,
        label=item.label,
        sort_order=item.sort_order,
        created_at=item.created_at.isoformat()
    )


@router.get("/{habit_id}/items", response_model=List[HabitItemResponse])
def get_habit_items(
    habit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all checklist items for a habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    items = db.query(HabitItem).filter(
        HabitItem.habit_id == habit_id
    ).order_by(HabitItem.sort_order).all()

    return [
        HabitItemResponse(
            id=item.id,
            habit_id=item.habit_id,
            label=item.label,
            sort_order=item.sort_order,
            created_at=item.created_at.isoformat()
        ) for item in items
    ]


@router.post("/{habit_id}/link", response_model=HabitLinkResponse)
def link_habit_to_resource(
    habit_id: str,
    link_data: HabitLinkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Link a habit to a note, document, or concept."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    existing_link = db.query(HabitLink).filter(
        HabitLink.habit_id == habit_id,
        HabitLink.target_type == link_data.target_type,
        HabitLink.target_id == link_data.target_id
    ).first()

    if existing_link:
        raise HTTPException(status_code=400, detail="Link already exists")

    link = HabitLink(
        habit_id=habit_id,
        target_type=link_data.target_type,
        target_id=link_data.target_id,
        meta=link_data.meta
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    return HabitLinkResponse(
        id=link.id,
        habit_id=link.habit_id,
        target_type=link.target_type,
        target_id=link.target_id,
        meta=link.meta,
        created_at=link.created_at.isoformat()
    )


@router.get("/{habit_id}/links", response_model=List[HabitLinkResponse])
def get_habit_links(
    habit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all links for a habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    links = db.query(HabitLink).filter(HabitLink.habit_id == habit_id).all()

    return [
        HabitLinkResponse(
            id=link.id,
            habit_id=link.habit_id,
            target_type=link.target_type,
            target_id=link.target_id,
            meta=link.meta,
            created_at=link.created_at.isoformat()
        ) for link in links
    ]


@router.get("/{habit_id}/history")
def get_habit_history(
    habit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 90
):
    """Get detailed history for a specific habit."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    instances = db.query(HabitInstance).filter(
        HabitInstance.habit_id == habit_id,
        HabitInstance.date >= start_date,
        HabitInstance.date <= end_date
    ).order_by(HabitInstance.date.desc()).all()

    logs = db.query(HabitLog).filter(
        HabitLog.habit_id == habit_id,
        HabitLog.ts >= datetime.combine(start_date, datetime.min.time()),
        HabitLog.ts <= datetime.combine(end_date, datetime.max.time())
    ).order_by(HabitLog.ts.desc()).all()

    return {
        "habit": {
            "id": habit.id,
            "title": habit.title,
            "type": habit.type,
            "target": habit.target_numeric,
            "unit": habit.unit
        },
        "period": {
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        },
        "instances": [
            {
                "date": instance.date.isoformat() if hasattr(instance.date, 'isoformat') else str(instance.date),
                "expected": bool(instance.expected),
                "status": instance.status,
                "progress": instance.progress,
                "total_amount": instance.total_amount,
                "target": instance.target,
                "window": instance.window
            } for instance in instances
        ],
        "logs": [
            {
                "id": log.id,
                "timestamp": log.ts.isoformat(),
                "source": log.source,
                "payload": log.payload
            } for log in logs
        ]
    }


@router.post("/{habit_id}/log-retro")
def log_habit_retro(
    habit_id: str,
    log_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Log a habit completion for a past date (retro logging)."""
    habit = db.query(Habit).filter(
        Habit.id == habit_id,
        Habit.user_id == current_user.id
    ).first()

    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    try:
        if "date" in log_data:
            target_date = datetime.fromisoformat(log_data["date"]).date()
        else:
            raise HTTPException(status_code=400, detail="Date is required for retro logging")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    days_ago = (date.today() - target_date).days
    if days_ago > habit.retro_hours / 24:
        raise HTTPException(
            status_code=400,
            detail=f"Retro logging only allowed within {habit.retro_hours} hours"
        )

    if target_date > date.today():
        raise HTTPException(status_code=400, detail="Cannot log for future dates")

    log = HabitLog(
        habit_id=habit_id,
        user_id=current_user.id,
        ts=datetime.combine(target_date, datetime.now().time()),
        source=log_data.get("source", "retro"),
        payload=json.dumps({
            "amount": log_data.get("amount"),
            "retro": True
        }) if log_data.get("amount") else json.dumps({"retro": True})
    )
    db.add(log)
    db.commit()

    # Update instance for that date if it exists
    from app.services.habit_instances import HabitInstanceGenerator

    instance_data = HabitInstanceGenerator.get_instance_by_habit_and_date(
        db, habit_id, target_date
    )

    if instance_data:
        target_logs = db.query(HabitLog).filter(
            HabitLog.habit_id == habit_id,
            HabitLog.ts >= datetime.combine(target_date, datetime.min.time()),
            HabitLog.ts < datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        ).all()

        log_dicts = [
            {"payload": l.payload, "ts": l.ts, "source": l.source}
            for l in target_logs
        ]

        checklist_items = []
        if habit.type == "checklist":
            items = db.query(HabitItem).filter(HabitItem.habit_id == habit_id).all()
            checklist_items = [{"id": item.id, "label": item.label} for item in items]

        HabitInstanceGenerator.update_instance_progress(
            db, instance_data["instance_id"], log_dicts, habit, checklist_items
        )

    if app_settings.temerant_enabled and app_settings.temerant_auto_ingestion_enabled:
        try:
            from app.services.temerant import CharacterService, IngestionService
            from app.services.temerant.rules_engine import TemerantRulesEngine

            character = CharacterService.get_character(db, current_user.id)
            if character:
                inferred_action = TemerantRulesEngine.infer_action_type(habit.title, fallback="study")
                IngestionService.log_external_action(
                    db=db,
                    user_id=current_user.id,
                    character=character,
                    source_type="habit",
                    source_ref_id=log.id,
                    mapping_ref=habit.id,
                    default_action_type=inferred_action,
                    action_label=habit.title,
                    notes="retro_log",
                    quantity=log_data.get("amount"),
                    occurred_at=log.ts,
                    metadata={"habit_id": habit.id, "habit_type": habit.type, "retro": True},
                )
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Temerant auto-ingestion failed for retro habit log")

    return {"message": f"Retro log created for {target_date}", "log_id": log.id}


# Separate router for habit_items and habit_links (flat routes)
habit_items_router = APIRouter(tags=["Habits"])


@habit_items_router.patch("/habit_items/{item_id}", response_model=HabitItemResponse)
def update_habit_item(
    item_id: str,
    item_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a checklist item."""
    item = db.query(HabitItem).join(Habit).filter(
        HabitItem.id == item_id,
        Habit.user_id == current_user.id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if "label" in item_data:
        item.label = item_data["label"]
    if "sort_order" in item_data:
        item.sort_order = item_data["sort_order"]

    db.commit()
    db.refresh(item)

    return HabitItemResponse(
        id=item.id,
        habit_id=item.habit_id,
        label=item.label,
        sort_order=item.sort_order,
        created_at=item.created_at.isoformat()
    )


@habit_items_router.delete("/habit_items/{item_id}")
def delete_habit_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a checklist item."""
    item = db.query(HabitItem).join(Habit).filter(
        HabitItem.id == item_id,
        Habit.user_id == current_user.id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(item)
    db.commit()

    return {"message": "Item deleted successfully"}


@habit_items_router.delete("/habit_links/{link_id}")
def delete_habit_link(
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a habit link."""
    link = db.query(HabitLink).join(Habit).filter(
        HabitLink.id == link_id,
        Habit.user_id == current_user.id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()

    return {"message": "Link deleted successfully"}


# Insights router (separate prefix)
insights_router = APIRouter(prefix="/insights", tags=["Habits"])


@insights_router.get("/habits", response_model=HabitInsightsResponse)
def get_habit_insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    period: str = "month"
):
    """Get habit analytics and insights."""
    days_map = {"week": 7, "month": 30, "year": 365}
    days = days_map.get(period, 30)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()

    total_completions = 0
    total_expected = 0
    current_streaks = 0
    longest_streak = 0
    habit_performance = []

    for habit in habits:
        instances = db.query(HabitInstance).filter(
            HabitInstance.habit_id == habit.id,
            HabitInstance.date >= start_date,
            HabitInstance.date <= end_date,
            HabitInstance.expected == 1
        ).all()

        expected_count = len(instances)
        completed_count = len([i for i in instances if i.status == "complete"])
        completion_rate = (completed_count / expected_count * 100) if expected_count > 0 else 0

        total_expected += expected_count
        total_completions += completed_count

        streak = db.query(HabitStreak).filter(HabitStreak.habit_id == habit.id).first()
        current_streak = streak.current_streak if streak else 0
        best_streak = streak.best_streak if streak else 0

        if current_streak > 0:
            current_streaks += 1
        if best_streak > longest_streak:
            longest_streak = best_streak

        habit_performance.append(HabitInsightsPerformance(
            habit_id=habit.id,
            title=habit.title,
            type=habit.type,
            completion_rate=completion_rate,
            current_streak=current_streak,
            best_streak=best_streak,
            total_completions=completed_count
        ))

    average_completion_rate = (total_completions / total_expected * 100) if total_expected > 0 else 0

    overview = HabitInsightsOverview(
        total_habits=len(habits),
        active_habits=len([h for h in habits if not h.paused]),
        total_completions=total_completions,
        average_completion_rate=average_completion_rate,
        current_streaks=current_streaks,
        longest_streak=longest_streak
    )

    # Weekly stats
    week_start = end_date - timedelta(days=7)
    last_week_start = week_start - timedelta(days=7)

    this_week_total = 0
    this_week_completed = 0
    for habit in habits:
        week_instances = db.query(HabitInstance).filter(
            HabitInstance.habit_id == habit.id,
            HabitInstance.date >= week_start,
            HabitInstance.date <= end_date,
            HabitInstance.expected == 1
        ).all()
        this_week_total += len(week_instances)
        this_week_completed += len([i for i in week_instances if i.status == "complete"])

    this_week_rate = (this_week_completed / this_week_total * 100) if this_week_total > 0 else 0

    last_week_total = 0
    last_week_completed = 0
    for habit in habits:
        week_instances = db.query(HabitInstance).filter(
            HabitInstance.habit_id == habit.id,
            HabitInstance.date >= last_week_start,
            HabitInstance.date < week_start,
            HabitInstance.expected == 1
        ).all()
        last_week_total += len(week_instances)
        last_week_completed += len([i for i in week_instances if i.status == "complete"])

    last_week_rate = (last_week_completed / last_week_total * 100) if last_week_total > 0 else 0

    if this_week_rate > last_week_rate + 5:
        trend = "up"
    elif this_week_rate < last_week_rate - 5:
        trend = "down"
    else:
        trend = "stable"

    weekly_stats = HabitInsightsWeeklyStats(
        this_week={"completed": this_week_completed, "total": this_week_total, "completion_rate": this_week_rate},
        last_week={"completed": last_week_completed, "total": last_week_total, "completion_rate": last_week_rate},
        trend=trend
    )

    most_consistent = habit_performance[0].title if habit_performance else "None"

    patterns = HabitInsightsPatterns(
        best_day_of_week="Monday",
        best_time_of_day="Morning",
        most_consistent_habit=most_consistent,
        improvement_suggestions=[
            "Try setting reminders for your habits",
            "Start with smaller, easier habits to build momentum",
            "Track your habits at the same time each day"
        ]
    )

    return HabitInsightsResponse(
        overview=overview,
        weekly_stats=weekly_stats,
        habit_performance=habit_performance,
        patterns=patterns
    )


# Fitness habits endpoints (stubs for backward compatibility)
fitness_habits_router = APIRouter(prefix="/fitness", tags=["Fitness"])


@fitness_habits_router.get("/habits")
async def get_fitness_habits(
    start_date: str = None,
    end_date: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get habit logs (stub for fitness integration)."""
    return []


@fitness_habits_router.get("/habits/streaks")
async def get_fitness_habit_streaks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get habit streaks for fitness tracking."""
    habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
    return [{
        "id": habit.id,
        "title": habit.title,
        "current_streak": habit.current_streak or 0,
        "best_streak": habit.best_streak or 0,
        "type": habit.type
    } for habit in habits]
