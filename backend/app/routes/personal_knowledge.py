"""
Personal Knowledge Graph (PKG) Browsing API

Allows browsing, searching, editing, and deleting PKG facts about David.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["personal-knowledge"])


class PKGNodeUpdate(BaseModel):
    """Update request for a PKG node"""
    confidence: Optional[float] = None
    properties: Optional[dict] = None


@router.get("/api/pkg/browse")
async def browse_pkg(
    current_user=Depends(get_current_user),
    category: Optional[str] = Query(None, description="Filter by category: Person, Preference, Routine, Goal, Interest, Health, Place, Fact"),
    search: Optional[str] = Query(None, description="Search query"),
    limit: int = Query(50, ge=1, le=200)
):
    """Browse the Personal Knowledge Graph by category or search"""
    try:
        from app.services.personal_knowledge_graph import personal_kg

        if search:
            facts = personal_kg.query_relevant([search], limit=limit)
        else:
            facts = personal_kg.browse(category=category, limit=limit)

        return {"facts": facts, "total": len(facts)}
    except Exception as e:
        logger.error(f"PKG browse failed: {e}")
        return {"facts": [], "total": 0, "error": str(e)}


@router.get("/api/pkg/stats")
async def pkg_stats(
    current_user=Depends(get_current_user),
):
    """Get PKG node counts and confidence distribution"""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        stats = personal_kg.get_stats()
        return stats
    except Exception as e:
        logger.error(f"PKG stats failed: {e}")
        return {"total": 0, "error": str(e)}


@router.get("/api/pkg/graph")
async def pkg_graph_data(
    current_user=Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500)
):
    """Get graph data for PKG visualization (nodes + edges)"""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        data = personal_kg.get_graph_data(limit=limit)
        return data
    except Exception as e:
        logger.error(f"PKG graph data failed: {e}")
        return {"nodes": [], "edges": [], "error": str(e)}


@router.delete("/api/pkg/{node_id}")
async def delete_pkg_node(
    node_id: str,
    current_user=Depends(get_current_user),
):
    """Delete a PKG node (David can remove incorrect facts)"""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        success = personal_kg.delete_node(node_id)
        if success:
            return {"success": True, "message": f"Deleted node {node_id}"}
        else:
            raise HTTPException(status_code=404, detail="Node not found or deletion failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PKG delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/pkg/{node_id}")
async def update_pkg_node(
    node_id: str,
    update: PKGNodeUpdate,
    current_user=Depends(get_current_user),
):
    """Update a PKG node (David can correct facts)"""
    try:
        from app.services.personal_knowledge_graph import personal_kg

        updates = {}
        if update.confidence is not None:
            updates["confidence"] = min(max(update.confidence, 0.0), 1.0)
        if update.properties:
            updates.update(update.properties)

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        success = personal_kg.update_node(node_id, updates)
        if success:
            return {"success": True, "message": f"Updated node {node_id}"}
        else:
            raise HTTPException(status_code=404, detail="Node not found or update failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PKG update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
