"""
Agent Orchestration Routes — REST API for VM agent dispatch and candidate skills.

Endpoints:
- POST /api/agents/dispatch — dispatch task to VM
- POST /api/agents/tasks/{task_id}/resume — resume agent session
- GET  /api/agents/tasks — list agent tasks
- GET  /api/agents/tasks/{task_id} — task detail
- POST /api/agents/vm/test — test VM SSH connection
- GET  /api/agents/skills/candidates — list candidate skills
- GET  /api/agents/skills/candidates/{id} — candidate detail
- POST /api/agents/skills/candidates/{id}/review — accept/reject/test
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db, SessionLocal
from app.core.deps import get_current_user
from app.core.auth import verify_token
from app.models.user import User

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

router = APIRouter(prefix="/api/agents", tags=["Agent Orchestration"])


# ── Request/Response Models ───────────────────────────────────────────

class DispatchRequest(BaseModel):
    task_description: str
    mode: str = "auto"  # auto | dispatch | sandbox | internal | self_orchestrate
    working_directory: Optional[str] = None
    timeout: int = 600


class ResumeRequest(BaseModel):
    instruction: str


class ReviewRequest(BaseModel):
    action: str  # accept | reject | test
    review_notes: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/dispatch")
async def dispatch_task(
    req: DispatchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Dispatch a task to a VM agent or self-orchestrate."""
    from app.services.agent_dispatch import agent_dispatch_service

    result = await agent_dispatch_service.dispatch_task(
        db=db,
        user_id=str(current_user.id),
        task_description=req.task_description,
        mode=req.mode,
        working_directory=req.working_directory,
        # NOTE: `timeout` is accepted in the request for client compat but the
        # dispatch service no longer takes it — the loop is round-capped.
    )
    return result


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    req: ResumeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resume an agent session with follow-up instruction."""
    from app.services.agent_dispatch import agent_dispatch_service

    result = await agent_dispatch_service.resume_task(
        db=db,
        task_id=task_id,
        user_id=str(current_user.id),
        instruction=req.instruction,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retry a failed agent task by creating a new task+mission."""
    from app.services.agent_dispatch import agent_dispatch_service

    result = await agent_dispatch_service.retry_task(
        db=db,
        task_id=task_id,
        user_id=str(current_user.id),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Cancel a running or pending agent task."""
    from app.services.agent_dispatch import agent_dispatch_service

    result = await agent_dispatch_service.cancel_task(
        db=db,
        task_id=task_id,
        user_id=str(current_user.id),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/tasks")
async def list_agent_tasks(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List agent tasks (vm_agent and self_orchestrate types)."""
    from app.services.agent_dispatch import agent_dispatch_service

    tasks = await agent_dispatch_service.get_agent_tasks(
        db=db,
        user_id=str(current_user.id),
        limit=limit,
    )
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_agent_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get full detail for a specific agent task."""
    from app.services.agent_dispatch import agent_dispatch_service

    detail = await agent_dispatch_service.get_task_detail(
        db=db,
        task_id=task_id,
        user_id=str(current_user.id),
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Task not found")
    return detail


@router.get("/tasks/{task_id}/stream")
async def stream_task_execution(
    task_id: str,
    request: Request,
    token: Optional[str] = Query(None),
):
    """SSE stream of real-time task execution events.
    Accepts auth via cookie, Authorization header, or ?token= query param.
    """
    # Authenticate with a SHORT-LIVED session that is released before the
    # long-lived stream begins. A request-scoped session (Depends(get_db)) would
    # stay open for the whole stream — minutes of idleness — and Postgres kills
    # it with "terminating connection due to idle-in-transaction timeout", which
    # crashes the stream teardown and forces the client into a reconnect loop
    # (the "no live logs" bug). The stream itself needs only Redis, not the DB.
    user = None
    auth_db = SessionLocal()
    try:
        try:
            user = await get_current_user(request, request.cookies.get("access_token"), auth_db)
        except Exception:
            pass

        if not user and token:
            payload = verify_token(token)
            if payload and payload.get("sub"):
                user = auth_db.query(User).filter(User.id == payload["sub"]).first()
    finally:
        auth_db.close()

    if not user:
        raise HTTPException(401, "Could not validate credentials")

    async def event_generator():
        r = None
        pubsub = None
        channel = f"sara:dispatch:live:{task_id}"
        try:
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(channel)
            logger.info(f"Dispatch live SSE connected: task={task_id}")

            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id})}\n\n"

            keepalive = 0
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.1
                )
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    keepalive = 0
                else:
                    await asyncio.sleep(0.4)
                    keepalive += 1
                    if keepalive >= 30:  # ~15s
                        yield f": keepalive\n\n"
                        keepalive = 0
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Dispatch live SSE error: {e}")
        finally:
            try:
                if pubsub:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
            except Exception:
                pass
            try:
                if r:
                    await r.close()
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/vm/test")
async def test_vm_connection(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Test SSH connection to the sandbox VM."""
    from app.services.vm_bridge import VMBridge, get_vm_config_from_settings
    from app.models.user_settings import UserSettings

    settings = db.query(UserSettings).filter(
        UserSettings.user_id == str(current_user.id)
    ).first()
    preferences = settings.preferences if settings else {}
    config = get_vm_config_from_settings(preferences)
    bridge = VMBridge(config)

    status = await bridge.test_connection()
    return {
        "status": status.value,
        "host": config.host,
        "username": config.username,
    }


# ── Candidate Skills ─────────────────────────────────────────────────

@router.get("/skills/candidates")
async def list_candidate_skills(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List candidate skills, optionally filtered by status."""
    from app.models.candidate_skill import CandidateSkill

    query = db.query(CandidateSkill).filter(
        CandidateSkill.user_id == str(current_user.id)
    )
    if status:
        query = query.filter(CandidateSkill.status == status)

    skills = query.order_by(CandidateSkill.created_at.desc()).limit(50).all()
    return {
        "candidates": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "contexts": s.contexts,
                "priority": s.priority,
                "status": s.status,
                "source_task_id": s.source_task_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
            }
            for s in skills
        ]
    }


@router.get("/skills/candidates/{skill_id}")
async def get_candidate_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get full detail for a candidate skill including instructions."""
    from app.models.candidate_skill import CandidateSkill

    skill = db.query(CandidateSkill).filter(
        CandidateSkill.id == skill_id,
        CandidateSkill.user_id == str(current_user.id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Candidate skill not found")

    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "instructions": skill.instructions,
        "contexts": skill.contexts,
        "priority": skill.priority,
        "status": skill.status,
        "source_mission_id": skill.source_mission_id,
        "source_task_id": skill.source_task_id,
        "vm_artifacts": skill.vm_artifacts,
        "review_notes": skill.review_notes,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "reviewed_at": skill.reviewed_at.isoformat() if skill.reviewed_at else None,
    }


@router.post("/skills/candidates/{skill_id}/review")
async def review_candidate_skill(
    skill_id: str,
    req: ReviewRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Accept, reject, or test a candidate skill."""
    from app.models.candidate_skill import CandidateSkill

    skill = db.query(CandidateSkill).filter(
        CandidateSkill.id == skill_id,
        CandidateSkill.user_id == str(current_user.id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Candidate skill not found")

    if req.action not in ("accept", "reject", "test"):
        raise HTTPException(status_code=400, detail="action must be accept, reject, or test")

    if req.action == "accept":
        # Promote to SKILL.md file
        try:
            skill_path = _create_skill_file(skill)
            skill.status = "accepted"
            skill.reviewed_at = datetime.now(timezone.utc)
            skill.review_notes = req.review_notes or f"Accepted. Skill file: {skill_path}"

            # Trigger hot reload via the skill watcher
            try:
                from app.skills import get_skill_loader
                loader = get_skill_loader()
                loader.reload_skill(Path(skill_path))
            except Exception as e:
                logger.warning(f"Skill hot-reload failed (will load on restart): {e}")

            db.commit()
            return {
                "status": "accepted",
                "skill_path": str(skill_path),
                "message": f"Skill '{skill.name}' promoted to {skill_path}",
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create skill file: {e}")

    elif req.action == "reject":
        skill.status = "rejected"
        skill.reviewed_at = datetime.now(timezone.utc)
        skill.review_notes = req.review_notes
        db.commit()
        return {"status": "rejected", "message": f"Skill '{skill.name}' rejected"}

    elif req.action == "test":
        skill.status = "testing"
        skill.review_notes = req.review_notes
        db.commit()
        return {"status": "testing", "message": f"Skill '{skill.name}' marked for testing"}


def _create_skill_file(skill) -> str:
    """Create a SKILL.md file from a CandidateSkill record."""
    skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"
    skill_dir = skills_dir / skill.name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"

    contexts_yaml = ", ".join(skill.contexts) if skill.contexts else "chat"
    content = f"""---
name: {skill.name}
description: {skill.description}
contexts: [{contexts_yaml}]
enabled: true
priority: {skill.priority or 50}
requires: {{env: [], config: []}}
user_invocable: false
---
{skill.instructions}
"""

    skill_file.write_text(content, encoding="utf-8")
    logger.info(f"Created skill file: {skill_file}")
    return str(skill_file)
