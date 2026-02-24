"""
Personal Knowledge Graph (PKG) Browsing API

Allows browsing, searching, editing, and deleting PKG facts about David.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["personal-knowledge"])

VALID_FACT_TYPES = ["Person", "Preference", "Routine", "Goal", "Interest", "Health", "Place", "Fact"]


class PKGNodeUpdate(BaseModel):
    """Update request for a PKG node"""
    confidence: Optional[float] = None
    properties: Optional[dict] = None


class PKGReviewedRequest(BaseModel):
    """Request body for marking a PKG node as reviewed"""
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="New confidence value after review")


class PKGNodeCreate(BaseModel):
    """Create request for a new PKG node"""
    fact_type: str = Field(..., description="One of: Person, Preference, Routine, Goal, Interest, Health, Place, Fact")
    properties: dict = Field(..., description="Domain-specific properties for the node")
    confidence: float = Field(0.9, ge=0.0, le=1.0, description="User-entered gets high confidence")


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


@router.post("/api/pkg/node")
async def create_pkg_node(
    body: PKGNodeCreate,
    current_user=Depends(get_current_user),
):
    """Create a new PKG node (user-initiated manual add)"""
    if body.fact_type not in VALID_FACT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fact_type '{body.fact_type}'. Must be one of: {', '.join(VALID_FACT_TYPES)}"
        )

    try:
        from app.services.personal_knowledge_graph import personal_kg

        pkg_id = personal_kg.upsert_fact(
            fact_type=body.fact_type,
            properties=body.properties,
            confidence=body.confidence,
            source="user_explicit",
        )
        if pkg_id:
            return {"success": True, "pkg_id": pkg_id, "message": f"Created {body.fact_type} node"}
        else:
            raise HTTPException(status_code=500, detail="Failed to create PKG node")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PKG create failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/pkg/reextract")
async def reextract_pkg(
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    since_hours: int = Query(24, ge=1, le=168, description="Hours of history to re-extract from"),
):
    """Trigger manual re-extraction of PKG facts from recent conversations"""
    try:
        from app.tasks.autonomy import pkg_deep_extract

        user_id = str(current_user.id)
        pkg_deep_extract.delay(user_id=user_id, since_hours=since_hours)

        return {
            "success": True,
            "message": f"PKG re-extraction queued for last {since_hours} hours of conversations",
            "since_hours": since_hours,
        }
    except Exception as e:
        logger.error(f"PKG reextract trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/pkg/summary")
async def pkg_summary(
    current_user=Depends(get_current_user),
):
    """Get a natural language summary of what Sara knows about David"""
    try:
        from app.services.personal_knowledge_graph import personal_kg

        stats = personal_kg.get_stats()
        total = stats.get("total", 0)
        by_type = stats.get("by_type", {})
        conf_dist = stats.get("confidence_distribution", {})

        if total == 0:
            return {
                "summary": "Sara doesn't know much about you yet. Keep chatting and she'll learn!",
                "total": 0,
                "stats": stats,
                "highlights": [],
            }

        # Build summary text
        parts = [f"Sara knows {total} things about you"]

        high = conf_dist.get("high", 0)
        medium = conf_dist.get("medium", 0)
        low = conf_dist.get("low", 0)
        if high:
            parts.append(f"{high} high confidence")
        if medium:
            parts.append(f"{medium} moderate")
        if low:
            parts.append(f"{low} need verification")

        summary_line = parts[0]
        if len(parts) > 1:
            summary_line += " (" + ", ".join(parts[1:]) + ")"
        summary_line += "."

        # Category breakdown
        type_lines = []
        type_labels = {
            "Person": "people",
            "Preference": "preferences",
            "Routine": "routines",
            "Goal": "goals",
            "Interest": "interests",
            "Health": "health facts",
            "Place": "places",
            "Fact": "general facts",
        }
        for t, label in type_labels.items():
            count = by_type.get(t, 0)
            if count > 0:
                type_lines.append(f"{count} {label}")

        if type_lines:
            summary_line += " Including: " + ", ".join(type_lines) + "."

        # Get a few example highlights from each populated category
        highlights = []
        for fact_type in VALID_FACT_TYPES:
            if by_type.get(fact_type, 0) > 0:
                sample = personal_kg.browse(category=fact_type, limit=2)
                for item in sample:
                    formatted = personal_kg._format_fact_natural(
                        item.get("type", fact_type), item
                    )
                    if formatted:
                        highlights.append({
                            "type": fact_type,
                            "text": formatted,
                            "confidence": item.get("confidence", 0),
                        })

        return {
            "summary": summary_line,
            "total": total,
            "stats": stats,
            "highlights": highlights[:12],
        }
    except Exception as e:
        logger.error(f"PKG summary failed: {e}")
        return {
            "summary": "Unable to generate summary at this time.",
            "total": 0,
            "stats": {},
            "highlights": [],
            "error": str(e),
        }


@router.get("/api/pkg/needs-review")
async def pkg_needs_review(
    current_user=Depends(get_current_user),
):
    """Get PKG nodes flagged for review (potential contradictions or staleness)"""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        items = personal_kg.get_needs_review()
        return {"items": items, "count": len(items)}
    except Exception as e:
        logger.error(f"PKG needs-review failed: {e}")
        return {"items": [], "count": 0, "error": str(e)}


@router.post("/api/pkg/{node_id}/reviewed")
async def mark_pkg_reviewed(
    node_id: str,
    body: PKGReviewedRequest = PKGReviewedRequest(),
    current_user=Depends(get_current_user),
):
    """Mark a PKG node as reviewed (clear needs_review flag, optionally update confidence)"""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        success = personal_kg.mark_reviewed(node_id, new_confidence=body.confidence)
        if success:
            return {"success": True, "message": f"Node {node_id} marked as reviewed"}
        else:
            raise HTTPException(status_code=404, detail="Node not found or review failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PKG mark-reviewed failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/pkg/validation-report")
async def pkg_validation_report(
    current_user=Depends(get_current_user),
):
    """
    Get the latest PKG validation report.
    Reads from working memory (stored after evening consolidation).
    Falls back to running a fresh validation if no stored report is found.
    """
    import json

    user_id = str(current_user.id)

    # Try to read from working memory first
    try:
        from app.services.working_memory import read_memory
        memory = await read_memory(user_id)
        stored_report = getattr(memory, "pkg_validation_report", None)
        if stored_report:
            if isinstance(stored_report, str):
                report = json.loads(stored_report)
            else:
                report = stored_report
            report["source"] = "cached"
            return report
    except Exception as e:
        logger.debug(f"PKG validation report: could not read from working memory: {e}")

    # No cached report — run a fresh validation (fast, no LLM)
    try:
        from app.services.personal_knowledge_graph import personal_kg
        report = personal_kg.validate_against_recent()
        report["source"] = "fresh"

        # Return a summary (don't include full contradiction evidence in the API)
        return {
            "confirmed": report.get("confirmed", 0),
            "contradictions_count": len(report.get("contradictions", [])),
            "contradictions": [
                {
                    "node_id": c["node_id"],
                    "fact_type": c.get("fact_type", ""),
                    "fact_summary": c["fact_summary"],
                    "confidence": c.get("confidence", 0),
                }
                for c in report.get("contradictions", [])
            ],
            "stale": report.get("stale", 0),
            "total_checked": report.get("total_checked", 0),
            "validated_at": report.get("validated_at", ""),
            "source": "fresh",
        }
    except Exception as e:
        logger.error(f"PKG validation report failed: {e}")
        return {
            "confirmed": 0,
            "contradictions_count": 0,
            "contradictions": [],
            "stale": 0,
            "total_checked": 0,
            "source": "error",
            "error": str(e),
        }
