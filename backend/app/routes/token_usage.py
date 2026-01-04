"""
Token Usage API Routes
Track and display token consumption statistics
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from sqlalchemy.orm import Session
from app.main_simple import get_db, get_current_user
from app.services.token_usage_service import (
    get_token_stats,
    reset_token_stats,
    get_usage_breakdown
)

router = APIRouter(tags=["token-usage"])
logger = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================

class TokenStatsResponse(BaseModel):
    """Token usage statistics"""
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_requests: int
    last_reset_at: Optional[str] = None
    updated_at: Optional[str] = None


class UsageBreakdownItem(BaseModel):
    """Usage breakdown by model/operation"""
    model: str
    operation_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_count: int


class UsageBreakdownResponse(BaseModel):
    """Usage breakdown response"""
    period_days: int
    breakdown: List[UsageBreakdownItem]


class ResetResponse(BaseModel):
    """Reset confirmation"""
    success: bool
    message: str


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/stats", response_model=TokenStatsResponse)
async def get_stats(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get aggregate token usage statistics"""
    user_id = current_user.id if current_user else None
    stats = get_token_stats(db, user_id=user_id)
    return TokenStatsResponse(**stats)


@router.get("/breakdown", response_model=UsageBreakdownResponse)
async def get_breakdown(
    days: int = 30,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get token usage breakdown by model and operation type"""
    user_id = current_user.id if current_user else None
    breakdown = get_usage_breakdown(db, user_id=user_id, days=days)
    return UsageBreakdownResponse(**breakdown)


@router.post("/reset", response_model=ResetResponse)
async def reset_stats_endpoint(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset token usage statistics (aggregate only, keeps detailed logs)"""
    user_id = current_user.id if current_user else None
    success = reset_token_stats(db, user_id=user_id)

    if success:
        return ResetResponse(success=True, message="Token statistics have been reset")
    else:
        raise HTTPException(status_code=500, detail="Failed to reset token statistics")
