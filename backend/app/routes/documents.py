from fastapi import APIRouter, Depends
from app.core.deps import get_current_user
from app.models.user import User
from . import docs

router = APIRouter()

# Re-export all document endpoints from docs module
@router.get("/")
async def get_documents(current_user: User = Depends(get_current_user)):
    """Get all documents - proxy to docs endpoint"""
    from app.routes.docs import list_documents
    return await list_documents(current_user=current_user)

@router.get("/search")
async def search_documents(current_user: User = Depends(get_current_user)):
    """Search documents - proxy to docs endpoint"""
    # Return empty results for now
    return {"documents": [], "total": 0}