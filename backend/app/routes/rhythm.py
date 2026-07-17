"""Daily Rhythm Engine — read-only API for the learned model of David's typical day."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.deps import get_current_user
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rhythm", tags=["Daily Rhythm"])


def _row_to_dict(row) -> dict:
    return {
        "rhythm_key": row.rhythm_key,
        "day_scope": row.day_scope,
        "window_start": row.window_start.strftime("%H:%M") if row.window_start else None,
        "window_end": row.window_end.strftime("%H:%M") if row.window_end else None,
        "median_time": row.median_time.strftime("%H:%M") if row.median_time else None,
        "confidence": row.confidence,
        "sample_count": row.sample_count,
        "variance_minutes": row.variance_minutes,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


@router.get("")
async def get_rhythm(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The full learned rhythm — every rhythm_key/day_scope row, plus the
    current one-line summary. Place-specific rows (rhythm_key='place:<id>')
    are joined against known_place for a display name."""
    rows = db.execute(text("""
        SELECT dr.rhythm_key, dr.day_scope, dr.window_start, dr.window_end, dr.median_time,
               dr.confidence, dr.sample_count, dr.variance_minutes, dr.computed_at,
               kp.name AS place_name
        FROM daily_rhythm dr
        LEFT JOIN known_place kp ON dr.rhythm_key = 'place:' || kp.id
        WHERE dr.user_id = :uid
        ORDER BY dr.rhythm_key, dr.day_scope
    """), {"uid": current_user.id}).fetchall()

    core = []
    places = []
    for r in rows:
        d = _row_to_dict(r)
        if r.rhythm_key.startswith("place:"):
            d["place_name"] = r.place_name
            places.append(d)
        else:
            core.append(d)

    from app.services.daily_rhythm import build_rhythm_summary
    summary = build_rhythm_summary(db, current_user.id)

    return {"summary": summary, "core": core, "places": places}
