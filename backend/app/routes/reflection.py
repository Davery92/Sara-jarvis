from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import logging

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.reflection import (
    ReflectionStartResponse,
    ReflectionResponseRequest,
    ReflectionResponseReply,
    ReflectionHistoryResponse,
    ReflectionInsightsResponse,
    ReflectionSettingsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

try:
    from app.services.reflection_service import ReflectionService
    REFLECTION_SERVICE_AVAILABLE = True
except ImportError:
    REFLECTION_SERVICE_AVAILABLE = False


@router.post("/reflection/start", response_model=ReflectionStartResponse)
async def start_reflection(
    reflection_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a new daily reflection"""
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    reflection_service = ReflectionService(db)
    try:
        parsed_date = None
        if reflection_date:
            from datetime import date
            parsed_date = date.fromisoformat(reflection_date)
        result = await reflection_service.start_reflection(
            user_id=str(current_user.id), reflection_date=parsed_date
        )
        return ReflectionStartResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start reflection: {e}")
        raise HTTPException(status_code=500, detail="Failed to start reflection")


@router.post("/reflection/{reflection_id}/respond", response_model=ReflectionResponseReply)
async def respond_to_reflection_question(
    reflection_id: str,
    request: ReflectionResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Respond to a reflection question"""
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    reflection_service = ReflectionService(db)
    try:
        result = await reflection_service.respond_to_question(
            reflection_id=reflection_id,
            user_id=str(current_user.id),
            question_id=request.question_id,
            response=request.response,
            question_index=request.question_index,
        )
        return ReflectionResponseReply(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process reflection response: {e}")
        raise HTTPException(status_code=500, detail="Failed to process response")


@router.get("/reflection/history", response_model=ReflectionHistoryResponse)
async def get_reflection_history(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's reflection history"""
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    reflection_service = ReflectionService(db)
    try:
        result = await reflection_service.get_reflection_history(
            user_id=str(current_user.id), limit=limit, offset=offset
        )
        return ReflectionHistoryResponse(**result)
    except Exception as e:
        logger.error(f"Failed to get reflection history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve reflection history")


@router.get("/reflection/{reflection_id}/insights", response_model=ReflectionInsightsResponse)
async def get_reflection_insights(
    reflection_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get insights for a specific reflection"""
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    reflection_service = ReflectionService(db)
    try:
        result = await reflection_service.get_reflection_insights(
            reflection_id=reflection_id, user_id=str(current_user.id)
        )
        return ReflectionInsightsResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get reflection insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve insights")


@router.post("/reflection/settings")
async def update_reflection_settings(
    request: ReflectionSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update reflection settings"""
    if not REFLECTION_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Reflection service not available")
    reflection_service = ReflectionService(db)
    try:
        result = await reflection_service.update_reflection_settings(
            user_id=str(current_user.id), settings_data=request.dict(exclude_none=True)
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update reflection settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings")
