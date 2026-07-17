"""
Research plan API routes.

Endpoints for creating, monitoring, and managing research plans,
and for Sara to answer agent questions.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db


def get_current_user_id() -> str:
    """Get current user ID."""
    import os
    return os.getenv("SOLO_USER_ID", "default-user")

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research-plans", tags=["research-plans"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ResearchStepCreate(BaseModel):
    title: str
    description: str
    instructions: Optional[str] = None


class ResearchPlanCreate(BaseModel):
    title: str
    objective: str
    steps: list[ResearchStepCreate]
    model_id: Optional[str] = "Qwen3.5-27B"


class SaraAnswerRequest(BaseModel):
    answer: str


# ─── Plan CRUD ───────────────────────────────────────────────────────────────

@router.post("")
async def create_research_plan(
    plan: ResearchPlanCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Create a new research plan."""
    plan_id = str(uuid.uuid4())

    steps = [
        {
            "title": s.title,
            "description": s.description,
            "instructions": s.instructions or s.description,
            "status": "pending",
            "findings": {},
        }
        for s in plan.steps
    ]

    db.execute(
        text("""
            INSERT INTO research_plan (id, user_id, title, objective, steps, model_id, created_by)
            VALUES (:id, :user_id, :title, :objective, CAST(:steps AS jsonb), :model_id, 'sara')
        """),
        {
            "id": plan_id,
            "user_id": user_id,
            "title": plan.title,
            "objective": plan.objective,
            "steps": json.dumps(steps),
            "model_id": plan.model_id,
        },
    )
    db.commit()

    return {"id": plan_id, "title": plan.title, "status": "draft", "steps": len(steps)}


@router.get("")
async def list_research_plans(
    status: Optional[str] = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List research plans, optionally filtered by status."""
    params = {"user_id": user_id, "limit": limit}
    where = "WHERE user_id = :user_id"
    if status:
        where += " AND status = :status"
        params["status"] = status

    result = db.execute(
        text(f"""
            SELECT id, title, objective, status, current_step_index,
                   jsonb_array_length(steps) as total_steps,
                   model_id, total_tokens_used,
                   created_at, started_at, completed_at
            FROM research_plan
            {where}
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        params,
    )

    plans = []
    for row in result.fetchall():
        plans.append({
            "id": row.id,
            "title": row.title,
            "objective": row.objective[:200],
            "status": row.status,
            "current_step": row.current_step_index,
            "total_steps": row.total_steps,
            "model_id": row.model_id,
            "total_tokens_used": row.total_tokens_used,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        })

    return plans


@router.get("/{plan_id}")
async def get_research_plan(
    plan_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get full details of a research plan including steps and findings."""
    result = db.execute(
        text("SELECT * FROM research_plan WHERE id = :id AND user_id = :user_id"),
        {"id": plan_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Research plan not found")

    plan = dict(row._mapping)
    if isinstance(plan.get("steps"), str):
        plan["steps"] = json.loads(plan["steps"])

    # Serialize datetimes
    for field in ("created_at", "updated_at", "started_at", "completed_at"):
        val = plan.get(field)
        if val and hasattr(val, "isoformat"):
            plan[field] = val.isoformat()

    # Get messages for this plan
    msg_result = db.execute(
        text("""
            SELECT * FROM research_message
            WHERE plan_id = :plan_id
            ORDER BY created_at ASC
        """),
        {"plan_id": plan_id},
    )
    plan["messages"] = [
        {
            "id": m.id,
            "direction": m.direction,
            "content": m.content,
            "step_index": m.step_index,
            "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msg_result.fetchall()
    ]

    return plan


# ─── Execution Control ───────────────────────────────────────────────────────

@router.post("/{plan_id}/start")
async def start_research_plan(
    plan_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Start executing a research plan."""
    result = db.execute(
        text("SELECT status FROM research_plan WHERE id = :id AND user_id = :user_id"),
        {"id": plan_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Research plan not found")

    if row.status not in ("draft", "paused", "stuck"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start plan in status '{row.status}'",
        )

    # Dispatch Celery task
    from app.tasks.research import run_research_plan

    run_research_plan.delay(plan_id, user_id)

    return {"status": "started", "plan_id": plan_id}


@router.post("/{plan_id}/pause")
async def pause_research_plan(
    plan_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Pause a running research plan."""
    db.execute(
        text("""
            UPDATE research_plan
            SET status = 'paused', updated_at = NOW()
            WHERE id = :id AND user_id = :user_id AND status = 'running'
        """),
        {"id": plan_id, "user_id": user_id},
    )
    db.commit()
    return {"status": "paused", "plan_id": plan_id}


@router.delete("/{plan_id}")
async def delete_research_plan(
    plan_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Delete a research plan and its messages."""
    db.execute(
        text("DELETE FROM research_plan WHERE id = :id AND user_id = :user_id"),
        {"id": plan_id, "user_id": user_id},
    )
    db.commit()
    return {"deleted": True}


# ─── Sara ↔ Agent Messages ──────────────────────────────────────────────────

@router.get("/{plan_id}/messages")
async def get_research_messages(
    plan_id: str,
    status: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get messages between Sara and the research agent."""
    params = {"plan_id": plan_id, "user_id": user_id}
    status_filter = ""
    if status:
        status_filter = "AND rm.status = :status"
        params["status"] = status

    result = db.execute(
        text(f"""
            SELECT rm.* FROM research_message rm
            JOIN research_plan rp ON rp.id = rm.plan_id
            WHERE rm.plan_id = :plan_id AND rp.user_id = :user_id
            {status_filter}
            ORDER BY rm.created_at ASC
        """),
        params,
    )

    return [
        {
            "id": m.id,
            "direction": m.direction,
            "content": m.content,
            "step_index": m.step_index,
            "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "answered_at": m.answered_at.isoformat() if m.answered_at else None,
        }
        for m in result.fetchall()
    ]


@router.post("/{plan_id}/messages/{message_id}/answer")
async def answer_research_message(
    plan_id: str,
    message_id: str,
    body: SaraAnswerRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Manually answer a research agent's question (David or Sara)."""
    # Verify ownership
    result = db.execute(
        text("""
            SELECT rm.* FROM research_message rm
            JOIN research_plan rp ON rp.id = rm.plan_id
            WHERE rm.id = :msg_id AND rm.plan_id = :plan_id AND rp.user_id = :user_id
        """),
        {"msg_id": message_id, "plan_id": plan_id, "user_id": user_id},
    )
    msg = result.fetchone()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.status == "answered":
        raise HTTPException(status_code=400, detail="Already answered")

    # Store the answer
    answer_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO research_message (id, plan_id, direction, content, step_index, status)
            VALUES (:id, :plan_id, 'sara_to_agent', :content, :step_index, 'answered')
        """),
        {
            "id": answer_id,
            "plan_id": plan_id,
            "content": body.answer,
            "step_index": msg.step_index,
        },
    )

    # Mark original as answered
    db.execute(
        text("UPDATE research_message SET status = 'answered', answered_at = NOW() WHERE id = :id"),
        {"id": message_id},
    )
    db.commit()

    return {"answered": True, "answer_id": answer_id}


# ─── Research Files ──────────────────────────────────────────────────────────

@router.get("/{plan_id}/files")
async def list_research_files(
    plan_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List files created by the research agent."""
    result = db.execute(
        text("SELECT id FROM research_plan WHERE id = :id AND user_id = :user_id"),
        {"id": plan_id, "user_id": user_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Research plan not found")

    from app.services.research.tools import get_work_dir
    import os

    work_dir = get_work_dir(plan_id)
    files = []

    if os.path.exists(work_dir):
        for root, dirs, filenames in os.walk(work_dir):
            for f in filenames:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, work_dir)
                files.append({
                    "path": rel,
                    "size": os.path.getsize(full),
                    "modified": datetime.fromtimestamp(os.path.getmtime(full)).isoformat(),
                })

    return files


@router.get("/{plan_id}/files/{path:path}")
async def read_research_file(
    plan_id: str,
    path: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Read a file created by the research agent."""
    result = db.execute(
        text("SELECT id FROM research_plan WHERE id = :id AND user_id = :user_id"),
        {"id": plan_id, "user_id": user_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Research plan not found")

    from app.services.research.tools import get_work_dir
    import os

    work_dir = get_work_dir(plan_id)
    full_path = os.path.normpath(os.path.join(work_dir, path))

    if not full_path.startswith(work_dir):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(full_path, "r") as f:
        content = f.read()

    return {"path": path, "content": content}
