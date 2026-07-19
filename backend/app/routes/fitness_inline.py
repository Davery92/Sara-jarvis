"""Recovery log CRUD routes extracted from main_simple.py.

Food/workout stubs that were here have been removed — the iOS client
uses the real /api/fitness/* endpoints in routes/fitness.py, not these.
"""

import logging
from app.core.timezone import naive_local_now
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.deps import get_current_user
from app.db.session import SessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/fitness/recovery")
async def get_fitness_recovery(
    start_date: str = None,
    end_date: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get fitness recovery logs"""
    db = SessionLocal()
    try:
        from datetime import datetime, timedelta
        if not start_date:
            start_date = (naive_local_now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = naive_local_now().strftime("%Y-%m-%d")
        query = text("""
            SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours,
                   soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            FROM daily_recovery_log
            WHERE user_id = :user_id
              AND log_date >= :start_date
              AND log_date <= :end_date
            ORDER BY log_date DESC
        """)
        results = db.execute(query, {
            "user_id": current_user.id,
            "start_date": start_date,
            "end_date": end_date
        }).fetchall()
        recovery_logs = []
        for row in results:
            row_dict = row._mapping
            recovery_logs.append({
                "id": row_dict['id'],
                "user_id": row_dict['user_id'],
                "log_date": row_dict['log_date'].isoformat(),
                "logged_at": row_dict['created_at'].isoformat() if row_dict['created_at'] else None,
                "hrv": row_dict['hrv'],
                "heart_rate": row_dict['heart_rate'],
                "sleep_hours": float(row_dict['sleep_hours']) if row_dict['sleep_hours'] else None,
                "soreness_level": row_dict['soreness_level'],
                "body_weight": float(row_dict['body_weight']) if row_dict['body_weight'] else None,
                "weight_unit": row_dict['weight_unit'],
                "notes": row_dict['notes'],
                "created_at": row_dict['created_at'].isoformat() if row_dict['created_at'] else None,
                "updated_at": row_dict['updated_at'].isoformat() if row_dict['updated_at'] else None
            })
        return recovery_logs
    finally:
        db.close()


@router.post("/fitness/recovery")
async def create_fitness_recovery(
    recovery_data: dict,
    current_user: User = Depends(get_current_user)
):
    """Create fitness recovery log"""
    db = SessionLocal()
    try:
        from datetime import datetime
        log_date_str = recovery_data.get('log_date', naive_local_now().strftime("%Y-%m-%d"))
        soreness_level = recovery_data.get('soreness_level')
        if soreness_level is not None:
            if soreness_level < 1 or soreness_level > 10:
                raise HTTPException(status_code=400, detail="Soreness level must be between 1 and 10")
        try:
            log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        check_query = text("""
            SELECT id FROM daily_recovery_log
            WHERE user_id = :user_id AND log_date = :log_date
        """)
        existing = db.execute(check_query, {"user_id": current_user.id, "log_date": log_date}).fetchone()
        if existing:
            update_query = text("""
                UPDATE daily_recovery_log
                SET hrv = :hrv, heart_rate = :heart_rate, sleep_hours = :sleep_hours,
                    soreness_level = :soreness_level, body_weight = :body_weight,
                    weight_unit = :weight_unit, notes = :notes, updated_at = NOW()
                WHERE user_id = :user_id AND log_date = :log_date
                RETURNING id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            """)
            result = db.execute(update_query, {
                "user_id": current_user.id, "log_date": log_date,
                "hrv": recovery_data.get('hrv'), "heart_rate": recovery_data.get('heart_rate'),
                "sleep_hours": recovery_data.get('sleep_hours'), "soreness_level": recovery_data.get('soreness_level'),
                "body_weight": recovery_data.get('body_weight'),
                "weight_unit": recovery_data.get('weight_unit', 'lbs'),
                "notes": recovery_data.get('notes', '')
            }).fetchone()
        else:
            insert_query = text("""
                INSERT INTO daily_recovery_log
                (id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at)
                VALUES (:id, :user_id, :log_date, :hrv, :heart_rate, :sleep_hours, :soreness_level, :body_weight, :weight_unit, :notes, NOW(), NOW())
                RETURNING id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            """)
            result = db.execute(insert_query, {
                "id": str(uuid.uuid4()), "user_id": current_user.id, "log_date": log_date,
                "hrv": recovery_data.get('hrv'), "heart_rate": recovery_data.get('heart_rate'),
                "sleep_hours": recovery_data.get('sleep_hours'), "soreness_level": recovery_data.get('soreness_level'),
                "body_weight": recovery_data.get('body_weight'),
                "weight_unit": recovery_data.get('weight_unit', 'lbs'),
                "notes": recovery_data.get('notes', '')
            }).fetchone()
        db.commit()
        row = result._mapping
        return {
            "id": row['id'], "user_id": row['user_id'],
            "log_date": row['log_date'].isoformat(),
            "logged_at": row['created_at'].isoformat() if row['created_at'] else None,
            "hrv": row['hrv'], "heart_rate": row['heart_rate'],
            "sleep_hours": float(row['sleep_hours']) if row['sleep_hours'] else None,
            "soreness_level": row['soreness_level'],
            "body_weight": float(row['body_weight']) if row['body_weight'] else None,
            "weight_unit": row['weight_unit'], "notes": row['notes'],
            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save recovery log: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/fitness/recovery/{id}")
async def delete_fitness_recovery(
    id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete fitness recovery log"""
    db = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM daily_recovery_log
            WHERE id = :id AND user_id = :user_id
        """)
        db.execute(delete_query, {"id": id, "user_id": current_user.id})
        db.commit()
        return {"message": "Recovery log deleted"}
    finally:
        db.close()
