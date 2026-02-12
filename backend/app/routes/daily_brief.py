"""Daily brief routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Daily Brief"])

# Lazy-init daily brief service
_daily_brief_service = None
_service_attempted = False


def _get_daily_brief_service():
    global _daily_brief_service, _service_attempted
    if not _service_attempted:
        _service_attempted = True
        try:
            from app.services.morning_brief_service import daily_brief_service
            _daily_brief_service = daily_brief_service
        except (ImportError, Exception) as e:
            logger.warning(f"Daily Brief service not available: {e}")
    return _daily_brief_service


@router.get("/api/daily-brief/stats")
async def get_daily_brief_stats(
    current_user: User = Depends(get_current_user)
):
    """Get statistics about the user's daily brief system"""
    service = _get_daily_brief_service()
    if not service:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    try:
        stats = service.get_brief_stats(current_user.id)
        stats["is_bootstrapped"] = service.has_stable_layer(current_user.id)
        return stats
    except Exception as e:
        logger.error(f"Failed to get daily brief stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve stats")


@router.post("/api/daily-brief/bootstrap")
async def bootstrap_daily_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger bootstrap of the stable layer from conversation history"""
    service = _get_daily_brief_service()
    if not service:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    try:
        success = await service.bootstrap_stable_layer(current_user.id, db)
        return {
            "success": success,
            "message": "Stable layer bootstrapped successfully" if success else "Bootstrap failed - check logs"
        }
    except Exception as e:
        logger.error(f"Failed to bootstrap daily brief: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/daily-brief/compiled")
async def get_compiled_brief(
    current_user: User = Depends(get_current_user)
):
    """Get the current compiled daily brief (for debugging/inspection)"""
    service = _get_daily_brief_service()
    if not service:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    try:
        brief = await service.get_compiled_brief(current_user.id)
        return {
            "content": brief,
            "length": len(brief) if brief else 0
        }
    except Exception as e:
        logger.error(f"Failed to get compiled brief: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve brief")


@router.get("/api/daily-brief/layers/{layer_name}")
async def get_brief_layer(
    layer_name: str,
    current_user: User = Depends(get_current_user)
):
    """Get a specific layer of the daily brief"""
    service = _get_daily_brief_service()
    if not service:
        raise HTTPException(status_code=503, detail="Daily Brief service not available")

    valid_layers = ["moment", "day", "context", "stable"]
    if layer_name not in valid_layers:
        raise HTTPException(status_code=400, detail=f"Invalid layer. Must be one of: {valid_layers}")

    try:
        content = service._read_layer(current_user.id, layer_name)
        return {
            "layer": layer_name,
            "content": content,
            "length": len(content)
        }
    except Exception as e:
        logger.error(f"Failed to get layer {layer_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve layer")
