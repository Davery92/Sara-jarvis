"""
"Sara's model of you" panel (Desktop Jarvis Overhaul C4).

Surfaces learned behavioral patterns, rhythm windows, and recent ML
predictions in plain language, with Confirm/Wrong/Stop-using-this actions
that feed straight back into the same tables the training/detection loops
already read from — this is what makes correcting Sara's model of you
possible, not just visible.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main_simple import get_current_user, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/model-of-you", tags=["model-of-you"])


class PatternFeedbackInput(BaseModel):
    action: str  # "confirm" | "wrong" | "stop"
    response_text: Optional[str] = None


@router.get("")
async def get_model_of_you(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Learned patterns + rhythm windows + recent model predictions, for the
    Settings > Intelligence panel and overlay kind `patterns`."""
    user_id = str(current_user.id)

    from app.services.behavioral_pattern_service import behavioral_pattern_service
    patterns = await behavioral_pattern_service.get_active_patterns(db, user_id)

    rhythm_rows = db.execute(text("""
        SELECT rhythm_key, day_scope, window_start, window_end, median_time,
               confidence, sample_count, computed_at
        FROM daily_rhythm
        WHERE user_id = :user_id AND confidence >= 0.2
        ORDER BY confidence DESC
    """), {"user_id": user_id}).fetchall()

    from app.services.ml.control_plane import get_model_registry
    model_registry = get_model_registry()

    recent_predictions = db.execute(text("""
        SELECT model_family, model_version, prediction, mode, created_at
        FROM ml_prediction_log
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT 20
    """), {"user_id": user_id}).fetchall()

    return {
        "patterns": [
            {
                "id": p["id"],
                "description": p["description"],
                "category": p["category"],
                "confidence": p["confidence"],
                "status": p["status"],
                "times_accepted": p["times_accepted"],
                "times_rejected": p["times_rejected"],
            }
            for p in patterns
        ],
        "rhythm_windows": [
            {
                "rhythm_key": r.rhythm_key,
                "day_scope": r.day_scope,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
                "median_time": r.median_time.isoformat() if r.median_time else None,
                "confidence": r.confidence,
                "sample_count": r.sample_count,
            }
            for r in rhythm_rows
        ],
        "models": {
            family: {
                "active_version": entry.get("active_version"),
                "candidate_count": len([v for v in entry.get("versions", []) if v.get("status") == "candidate"]),
                "latest_metrics": (entry.get("versions") or [{}])[-1].get("metrics") if entry.get("versions") else None,
            }
            for family, entry in model_registry.items()
            if isinstance(entry, dict) and "versions" in entry
        },
        "recent_predictions": [
            {
                "model_family": r.model_family,
                "model_version": r.model_version,
                "prediction": r.prediction,
                "mode": r.mode,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_predictions
        ],
    }


@router.post("/patterns/{pattern_id}/feedback")
async def submit_pattern_feedback(
    pattern_id: str,
    payload: PatternFeedbackInput,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Confirm/Wrong feed the existing accept/reject counters (same path as
    a suggestion response); Stop sets status='dormant' immediately rather
    than waiting for the rejection-count threshold — an explicit "stop
    using this" shouldn't need repeating."""
    from app.services.behavioral_pattern_service import behavioral_pattern_service

    owner = db.execute(text(
        "SELECT user_id FROM behavioral_pattern WHERE id = :pattern_id"
    ), {"pattern_id": pattern_id}).fetchone()
    if not owner:
        raise HTTPException(status_code=404, detail="Pattern not found")
    if str(owner.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your pattern")

    if payload.action == "confirm":
        await behavioral_pattern_service.record_response(db, pattern_id, accepted=True, user_response=payload.response_text)
    elif payload.action == "wrong":
        await behavioral_pattern_service.record_response(db, pattern_id, accepted=False, user_response=payload.response_text)
    elif payload.action == "stop":
        db.execute(text("""
            UPDATE behavioral_pattern
            SET status = 'dormant', user_feedback = :feedback, updated_at = NOW()
            WHERE id = :pattern_id
        """), {"pattern_id": pattern_id, "feedback": payload.response_text or "user stopped this pattern"})
        db.commit()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {payload.action}")

    return {"status": "ok", "pattern_id": pattern_id, "action": payload.action}
