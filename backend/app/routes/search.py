from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from app.core.deps import get_current_user
from app.models.user import User
from app.services.search_service import search_service

router = APIRouter(prefix="/search", tags=["search"])

@router.get("/open_page")
async def open_page(url: str, current_user: User = Depends(get_current_user)):
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    try:
        data = await search_service.open_page(url)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open page: {e}")

